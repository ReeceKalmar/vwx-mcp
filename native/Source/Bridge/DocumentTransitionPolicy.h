#pragma once

#include "MaintenancePolicy.h"
#include <set>

namespace VwxBridge::DocumentTransition
{
    inline constexpr std::int32_t kRevision = 1;
    enum class Code : std::int32_t
    {
        Accepted = 1, InvalidContext = -201, InvalidArguments = -202,
        InventoryUnavailable = -203, UnsafeDocuments = -204, SourceMismatch = -205,
        WorkingFile = -206, TargetUnavailable = -207, Busy = -208,
        Consumed = -209, DocumentChanged = -210, SaveFailed = -211,
        TransitionFailed = -212, Unconfirmed = -213, NativeException = -214,
        MenuUnconfirmed = -215
    };

    enum class Phase { Idle, Staged, Executing, Completed, Failed, Uncertain };
    inline const char* PhaseName(Phase phase)
    {
        switch (phase) {
            case Phase::Idle: return "idle";
            case Phase::Staged: return "staged";
            case Phase::Executing: return "executing";
            case Phase::Completed: return "completed";
            case Phase::Failed: return "failed";
            default: return "uncertain";
        }
    }

    inline bool ValidRequestId(const std::wstring& id)
    {
        if (id.size() != 64) return false;
        for (wchar_t c : id)
            if (!((c >= L'0' && c <= L'9') || (c >= L'a' && c <= L'f'))) return false;
        return true;
    }

    struct State
    {
        Phase phase = Phase::Idle;
        Code code = Code::Accepted;
        std::wstring request, source, target;
        Maintenance::Documents before;
        std::int32_t sourceRef = -1, targetRef = -1;
        bool dispatched = false, saveConfirmed = false, transitionDispatched = false;
        std::uint64_t invocation = 0, stagedInvocation = 0;
        std::set<std::wstring> consumed;

        bool Begin(std::uint64_t token)
        {
            if (!token || invocation || phase == Phase::Executing) return false;
            invocation = token;
            return true;
        }

        Code Fail(Code failure)
        {
            code = failure;
            phase = dispatched ? Phase::Uncertain : Phase::Failed;
            return failure;
        }

        template<class Host>
        Code Inventory(Host& host, Maintenance::Documents& documents, bool requireSource)
        {
            if (!host.ContextReady()) return Code::InvalidContext;
            if (!host.ReadDocuments(documents)) return Code::InventoryUnavailable;
            if (documents.empty() || documents.size() > 256) return Code::UnsafeDocuments;
            size_t activeCount = 0;
            for (size_t i = 0; i < documents.size(); ++i)
            {
                auto& doc = documents[i];
                if (doc.fileRef < 0 || doc.inMemoryOnly) return Code::UnsafeDocuments;
                std::wstring normalized;
                if (!doc.inMemoryOnly)
                {
                    if (!Maintenance::NormalizeVwxPath(doc.path, normalized)) return Code::UnsafeDocuments;
                    doc.path = normalized;
                }
                for (size_t j = 0; j < i; ++j)
                {
                    const auto& prior = documents[j];
                    if (prior.fileRef == doc.fileRef || (!prior.inMemoryOnly && !doc.inMemoryOnly
                        && host.PathsEqual(prior.path, doc.path))) return Code::UnsafeDocuments;
                }
                if (doc.active)
                {
                    ++activeCount;
                    if (doc.inMemoryOnly) return Code::UnsafeDocuments;
                    if (!host.PathsEqual(doc.path, requireSource ? source : target)) return Code::SourceMismatch;
                }
            }
            if (activeCount != 1) return Code::UnsafeDocuments;
            if (!host.ContextReady()) return Code::InvalidContext;
            if (host.WorkingFile()) return Code::WorkingFile;
            if (!host.ContextReady()) return Code::InvalidContext;
            if (!host.ActiveFileMatches(requireSource ? source : target)) return Code::SourceMismatch;
            return host.ContextReady() ? Code::Accepted : Code::InvalidContext;
        }

        template<class Host>
        bool SameInventory(Host& host, const Maintenance::Documents& current) const
        {
            if (before.size() != current.size()) return false;
            for (const auto& old : before)
            {
                bool found = false;
                for (const auto& now : current)
                    if (old.fileRef == now.fileRef && old.active == now.active
                        && old.inMemoryOnly == now.inMemoryOnly && host.PathsEqual(old.path, now.path))
                    { found = true; break; }
                if (!found) return false;
            }
            return true;
        }

        template<class Host>
        Code Stage(Host& host, const std::wstring& from, const std::wstring& to, const std::wstring& id)
        {
            if (!host.ContextReady() || !invocation) return Code::InvalidContext;
            if (phase == Phase::Staged || phase == Phase::Executing || phase == Phase::Uncertain) return Code::Busy;
            std::wstring normalizedSource, normalizedTarget;
            if (!ValidRequestId(id) || !Maintenance::NormalizeVwxPath(from, normalizedSource)
                || !Maintenance::NormalizeVwxPath(to, normalizedTarget)
                || host.PathsEqual(normalizedSource, normalizedTarget)) return Code::InvalidArguments;
            if (consumed.find(id) != consumed.end()) return Code::Consumed;
            // This ID is consumed before any SDK inspection. It cannot be
            // staged again even if the host fails before a mutation begins.
            consumed.insert(id);
            request = id; source = normalizedSource; target = normalizedTarget;
            phase = Phase::Failed; code = Code::Accepted;
            dispatched = saveConfirmed = transitionDispatched = false;
            sourceRef = targetRef = -1; stagedInvocation = invocation;
            before.clear();
            try
            {
                auto checked = Inventory(host, before, true);
                if (checked != Code::Accepted) return Fail(checked);
                for (const auto& doc : before)
                {
                    if (doc.active) sourceRef = doc.fileRef;
                    if (!doc.inMemoryOnly && host.PathsEqual(doc.path, target)) targetRef = doc.fileRef;
                }
                if (!host.TargetExists(target)) return Fail(Code::TargetUnavailable);
                if (!host.ContextReady()) return Fail(Code::InvalidContext);
                phase = Phase::Staged;
                return Code::Accepted;
            }
            catch (...) { return Fail(Code::NativeException); }
        }

        template<class Host>
        void End(Host& host, std::uint64_t token, bool returnedAndCompleted)
        {
            if (!token || invocation != token) return;
            invocation = 0; // No callback/reentry may stage while SDK calls run.
            if (phase != Phase::Staged || stagedInvocation != token) return;
            if (!returnedAndCompleted) { Fail(Code::MenuUnconfirmed); return; }
            phase = Phase::Executing; // Consume before saving, including reentry.
            try
            {
                Maintenance::Documents current;
                auto checked = Inventory(host, current, true);
                if (checked != Code::Accepted || !SameInventory(host, current))
                { Fail(checked == Code::Accepted ? Code::DocumentChanged : checked); return; }
                if (!host.TargetExists(target)) { Fail(Code::TargetUnavailable); return; }
                // Target resolution can call the SDK. Inspect the complete
                // source identity once more immediately before its saved path
                // is used; no source/target basename or title matching exists.
                current.clear();
                checked = Inventory(host, current, true);
                if (checked != Code::Accepted || !SameInventory(host, current))
                { Fail(checked == Code::Accepted ? Code::DocumentChanged : checked); return; }
                if (!host.ContextReady()) { Fail(Code::InvalidContext); return; }
                dispatched = true;
                if (!host.Save()) { Fail(Code::SaveFailed); return; }
                saveConfirmed = true;
                current.clear();
                checked = Inventory(host, current, true);
                if (checked != Code::Accepted || !SameInventory(host, current))
                { Fail(checked == Code::Accepted ? Code::DocumentChanged : checked); return; }
                if (!host.ContextReady()) { Fail(Code::InvalidContext); return; }
                transitionDispatched = true;
                const bool accepted = targetRef >= 0 ? host.Switch(targetRef) : host.Open(target);
                // Never turn a failed/throwing switch into an open or retry.
                if (!accepted) { Fail(Code::TransitionFailed); return; }
                current.clear();
                checked = Inventory(host, current, false);
                if (checked != Code::Accepted) { Fail(checked); return; }
                // Switching keeps the complete set. Opening adds exactly one
                // target, while every prior source/reference remains present.
                if (current.size() != before.size() + (targetRef < 0 ? 1 : 0))
                { Fail(Code::Unconfirmed); return; }
                for (const auto& old : before)
                {
                    bool found = false;
                    for (const auto& now : current)
                        if (old.fileRef == now.fileRef && old.inMemoryOnly == now.inMemoryOnly
                            && host.PathsEqual(old.path, now.path)) { found = true; break; }
                    if (!found) { Fail(Code::Unconfirmed); return; }
                }
                for (const auto& doc : current)
                    if (doc.active)
                    {
                        if (doc.fileRef == sourceRef || (targetRef >= 0 && doc.fileRef != targetRef))
                        { Fail(Code::Unconfirmed); return; }
                        targetRef = doc.fileRef;
                    }
                code = Code::Accepted; phase = Phase::Completed;
            }
            catch (...) { Fail(Code::NativeException); }
        }

        std::string Json(std::uint32_t process) const
        {
            return "{\"schema_version\":1,\"process_id\":" + std::to_string(process)
                + ",\"request_id\":" + Maintenance::JsonString(request)
                + ",\"phase\":\"" + PhaseName(phase) + "\",\"source_path\":" + Maintenance::JsonString(source)
                + ",\"target_path\":" + Maintenance::JsonString(target)
                + ",\"code\":" + std::to_string(static_cast<std::int32_t>(code))
                + ",\"dispatched\":" + (dispatched ? "true" : "false")
                + ",\"save_confirmed\":" + (saveConfirmed ? "true" : "false")
                + ",\"transition_dispatched\":" + (transitionDispatched ? "true" : "false")
                + ",\"source_ref\":" + std::to_string(sourceRef)
                + ",\"target_ref\":" + std::to_string(targetRef) + "}";
        }
    };
}
