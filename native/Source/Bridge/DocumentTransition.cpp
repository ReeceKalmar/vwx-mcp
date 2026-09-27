#include "StdAfx.h"
#include "DocumentTransition.h"
#include "DocumentTransitionPolicy.h"

namespace VwxBridge::DocumentTransition
{
    namespace
    {
        State state;
        std::uint32_t brokerThread = 0;

        class Host
        {
        public:
            explicit Host(std::uint32_t thread) : fThread(thread) {}
            bool ContextReady() const
            {
                if (!fThread || GetCurrentThreadId() != fThread || !gSDK || !gCBP) return false;
                HWND frame = GS_GetMainHWND(gCBP);
                if (!frame || !IsWindow(frame)) return false;
                DWORD process = 0;
                return GetWindowThreadProcessId(frame, &process) == fThread && process == GetCurrentProcessId();
            }
            bool ReadDocuments(Maintenance::Documents& result) const
            {
                result.clear();
                VectorWorks::TVWArray_OpenFileInformation files;
                gSDK->GetOpenFilesList(files);
                if (files.GetSize() > 256) return false;
                for (size_t i = 0; i < files.GetSize(); ++i)
                {
                    const auto& file = files[i];
                    TXString path;
                    if (file.fpFileID)
                    {
                        if (file.fpFileID->GetFileFullPath(path) != kVCOMError_NoError) return false;
                    }
                    else if (!file.fIsInMemoryOnly) return false;
                    result.push_back({std::wstring(path.GetWCharPtr(), path.GetLength()), file.fFileRef,
                                      file.fIsActive, file.fIsInMemoryOnly});
                }
                return true;
            }
            bool PathsEqual(const std::wstring& a, const std::wstring& b) const
            {
                return CompareStringOrdinal(a.data(), static_cast<int>(a.size()),
                                            b.data(), static_cast<int>(b.size()), TRUE) == CSTR_EQUAL;
            }
            bool WorkingFile() const { return gSDK->IsAWorkingFile(); }
            bool ActiveFileMatches(const std::wstring& expected)
            {
                fActive.Release();
                bool saved = false, exists = false;
                if (!gSDK->GetActiveDocument(&fActive, saved) || !saved || !fActive) return false;
                TXString path;
                if (fActive->GetFileFullPath(path) != kVCOMError_NoError
                    || fActive->ExistsOnDisk(exists) != kVCOMError_NoError || !exists) return false;
                std::wstring normalized;
                return Maintenance::NormalizeVwxPath(std::wstring(path.GetWCharPtr(), path.GetLength()), normalized)
                    && PathsEqual(expected, normalized);
            }
            bool TargetExists(const std::wstring& path)
            {
                fTarget.Release();
                fTarget = VectorWorks::Filing::IFileIdentifierPtr(VectorWorks::Filing::IID_FileIdentifier);
                bool exists = false;
                return fTarget && fTarget->Set(TXString(path.c_str())) == kVCOMError_NoError
                    && fTarget->ExistsOnDisk(exists) == kVCOMError_NoError && exists;
            }
            bool Save() const { return fActive && gSDK->SaveActiveDocumentPath(fActive) == noError; }
            bool Switch(std::int32_t fileRef) const { return gSDK->SwitchToOpenFile(fileRef); }
            bool Open(const std::wstring&) const
            {
                // A fixed existing path with error-message UI disabled. This
                // flag is not a guarantee against every third-party dialog.
                return fTarget && gSDK->OpenDocumentPath(fTarget, false);
            }
        private:
            std::uint32_t fThread;
            VectorWorks::Filing::IFileIdentifierPtr fActive, fTarget;
        };
    }

    bool BeginMenu(std::uint32_t uiThread, std::uint64_t invocation)
    {
        Host host(uiThread);
        if (!host.ContextReady() || !state.Begin(invocation)) return false;
        brokerThread = uiThread;
        return true;
    }
    void EndMenu(std::uint64_t invocation, bool returnedAndCompleted)
    {
        Host host(brokerThread);
        state.End(host, invocation, returnedAndCompleted);
    }
    std::int32_t Revision(std::uint32_t registrationThread)
    {
        Host host(registrationThread);
        return host.ContextReady() ? kRevision : static_cast<std::int32_t>(Code::InvalidContext);
    }
    std::int32_t Stage(std::uint32_t registrationThread, const std::wstring& source,
                       const std::wstring& target, const std::wstring& request)
    {
        Host host(registrationThread);
        if (registrationThread != brokerThread) return static_cast<std::int32_t>(Code::InvalidContext);
        return static_cast<std::int32_t>(state.Stage(host, source, target, request));
    }
    std::string Status(std::uint32_t registrationThread)
    {
        Host host(registrationThread);
        if (!host.ContextReady())
            return "{\"schema_version\":1,\"process_id\":" + std::to_string(GetCurrentProcessId())
                + ",\"phase\":\"unavailable\",\"code\":-201}";
        return state.Json(GetCurrentProcessId());
    }
}
