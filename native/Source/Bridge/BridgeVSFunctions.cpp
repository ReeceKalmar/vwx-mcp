#include "StdAfx.h"

#include "BridgeVSFunctions.h"
#include "ArcAnglesPolicy.h"
#include "MaintenancePolicy.h"
#include "DocumentTransition.h"

using namespace VwxBridge;

namespace
{
    // SDK 3200 sample: TesterModule/Source/TesterModule/ExtVSFunc.cpp.
    // These are private bridge extensions, not additional SDK catalog APIs.
    const SFunctionDef kFunctions[] = {
        { "VWXBridgeRevision", "VWX Bridge", "Private bridge scripting ABI revision.",
          0, kVLIBScopeUniversal, true,
          { { "RETURN", kLongArgType } } },
        { "VWXBridgeSetArc", "VWX Bridge",
          "Set angles on an existing arc. Status 1 means the SDK call returned, not verified geometry.",
          0, kVLIBScopeUniversal, true,
          { { "h", kHandleArgType }, { "startDegrees", kRealArgType },
            { "sweepDegrees", kRealArgType }, { "RETURN", kLongArgType } } },
        { "VWXMaintRevision", "VWX Bridge", "Private maintenance ABI revision, with UI context check.",
          0, kVLIBScopeUniversal, true, { { "RETURN", kLongArgType } } },
        { "VWXMaintSnapshot", "VWX Bridge", "Read the SDK open-document inventory as JSON.",
          0, kVLIBScopeUniversal, true, { { "RETURN", kStringArgType } } },
        { "VWXMaintSave", "VWX Bridge", "Save the sole expected saved drawing and recheck its identity.",
          0, kVLIBScopeUniversal, true,
          { { "expectedPath", kStringArgType }, { "RETURN", kLongArgType } } },
        { "VWXMaintQuit", "VWX Bridge", "Save and recheck the sole expected drawing, then request normal quit with save prompts preserved.",
          0, kVLIBScopeUniversal, true,
          { { "expectedPath", kStringArgType }, { "RETURN", kLongArgType } } },
        { "VWXDocRevision", "VWX Bridge", "Private deferred document-transition ABI revision.",
          0, kVLIBScopeUniversal, true, { { "RETURN", kLongArgType } } },
        { "VWXDocStage", "VWX Bridge", "Stage an exact source/target transition for after this broker menu returns.",
          0, kVLIBScopeUniversal, true,
          { { "sourcePath", kStringArgType }, { "targetPath", kStringArgType },
            { "requestId", kStringArgType }, { "RETURN", kLongArgType } } },
        { "VWXDocStatus", "VWX Bridge", "Read the process-local transition outcome; independent inventory verification is required.",
          0, kVLIBScopeUniversal, true, { { "RETURN", kStringArgType } } },
        {}
    };

    static_assert(kHandleArgType == ArcAngles::kHandleArgument);
    static_assert(kRealArgType == ArcAngles::kRealArgument);
    static_assert(kArcNode == ArcAngles::kArcObjectType);
    static_assert(sizeof(wchar_t) == 2, "Windows UTF-16 is required for maintenance paths");

    class ArcHost
    {
    public:
        explicit ArcHost(DWORD registrationThread) : fRegistrationThread(registrationThread) {}

        bool ContextReady() const
        {
            // The host creates the scripting routine on its registration
            // thread. Reject a cross-thread caller before making any SDK call.
            if (GetCurrentThreadId() != fRegistrationThread || gSDK == nullptr || gCBP == nullptr)
                return false;
            HWND frame = GS_GetMainHWND(gCBP);
            if (!frame || !IsWindow(frame))
                return false;
            DWORD processId = 0;
            DWORD threadId = GetWindowThreadProcessId(frame, &processId);
            return processId == GetCurrentProcessId() && threadId == GetCurrentThreadId();
        }

        short ObjectType(MCObjectHandle handle) const
        {
            return gSDK->GetObjectTypeN(handle);
        }

        void SetAngles(MCObjectHandle handle, double startDegrees, double sweepDegrees) const
        {
            // SDK APIBase.Legacy.Defs.h: GS_SetArcAnglesN; VWArcObj::SetAngles
            // uses the same call with degrees. No replacement handle is made.
            // The shim returns void, so later independent jobs must verify it.
            GS_SetArcAnglesN(gCBP, handle, startDegrees, sweepDegrees);
        }

    private:
        DWORD fRegistrationThread;
    };

    class MaintenanceHost : public ArcHost
    {
    public:
        explicit MaintenanceHost(DWORD registrationThread) : ArcHost(registrationThread) {}

        bool ReadDocuments(Maintenance::Documents& result) const
        {
            result.clear();
            VectorWorks::TVWArray_OpenFileInformation files;
            gSDK->GetOpenFilesList(files);
            if (files.GetSize() > 256) return false;
            for (size_t i = 0; i < files.GetSize(); ++i)
            {
                const auto& file = files[i];
                if (file.fFileRef < 0) return false;
                for (const auto& prior : result)
                    if (prior.fileRef == file.fFileRef) return false;
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

        bool PathsEqual(const std::wstring& first, const std::wstring& second) const
        {
            return CompareStringOrdinal(first.data(), static_cast<int>(first.size()),
                                        second.data(), static_cast<int>(second.size()), TRUE) == CSTR_EQUAL;
        }

        bool WorkingFile() const { return gSDK->IsAWorkingFile(); }

        bool ActiveFileMatches(const std::wstring& expected)
        {
            fActiveFile.Release();
            bool previouslySaved = false;
            if (!gSDK->GetActiveDocument(&fActiveFile, previouslySaved) || !previouslySaved || !fActiveFile)
                return false;
            TXString path;
            bool exists = false;
            if (fActiveFile->GetFileFullPath(path) != kVCOMError_NoError
                || fActiveFile->ExistsOnDisk(exists) != kVCOMError_NoError || !exists)
                return false;
            std::wstring normalized;
            return Maintenance::NormalizeVwxPath(std::wstring(path.GetWCharPtr(), path.GetLength()), normalized)
                && PathsEqual(expected, normalized);
        }

        bool Save() const
        {
            // SDK GSError noError=0. The active file identifier has just been
            // independently matched to the sole expected open drawing.
            return fActiveFile && gSDK->SaveActiveDocumentPath(fActiveFile) == noError;
        }

        void Quit() const
        {
            // ISDK documents false as DISCARD all changes. Keep prompts even
            // after saving, in case a native callback/user made another edit.
            // The controller must observe exit, deploy, then launch separately.
            gSDK->CloseAllFilesAndQuitVectorworks(true, false);
        }

    private:
        VectorWorks::Filing::IFileIdentifierPtr fActiveFile;
    };

    std::string MaintenanceSnapshot(MaintenanceHost& host)
    {
        try
        {
            if (!host.ContextReady())
                return Maintenance::ErrorJson(GetCurrentProcessId(), Maintenance::Status::InvalidContext);
            Maintenance::Documents documents;
            if (!host.ReadDocuments(documents))
                return Maintenance::ErrorJson(GetCurrentProcessId(), Maintenance::Status::InventoryUnavailable);
            return Maintenance::SnapshotJson(GetCurrentProcessId(), documents);
        }
        catch (...) { return Maintenance::ErrorJson(GetCurrentProcessId(), Maintenance::Status::NativeException); }
    }
}

// This extension is called from vs.* within the existing Python menu job.
// Registration only describes routines; it runs no document or script work.
BEGIN_VWVSFunctions(CExtBridgeVSFunctions, "VWXBridgeNative", 1,
    0x8d92d336, 0xe9c3, 0x44d8, 0x9b, 0x24, 0xd9, 0x9a, 0x03, 0x55, 0xeb, 0x17);
ADD_VWVSFunctions_ROUTINE(CBridgeVSRoutines);
END_VWVSFunctions;

CExtBridgeVSFunctions::CExtBridgeVSFunctions(CallBackPtr cbp)
    : VWExtensionVSFunctions(cbp, kFunctions)
{
}

CExtBridgeVSFunctions::~CExtBridgeVSFunctions() = default;

CBridgeVSRoutines::CBridgeVSRoutines() : fRegistrationThread(GetCurrentThreadId())
{
}

void CBridgeVSRoutines::DispatchRoutine(Sint32 routineSelector, VWPluginLibraryArgTable& argTable)
{
    // Negative selectors are host initialization/teardown messages. Unlike
    // the SDK example's array-index dispatch, unknown selectors cannot index
    // the definition table or touch arguments.
    if (routineSelector < 0)
        return;

    PluginLibraryArgTable* raw = argTable;
    if (!raw)
        return; // No result channel exists on a malformed host dispatch.

    auto& result = argTable.GetResult();
    if (routineSelector == 8)
    {
        result.SetArgString(TXString(DocumentTransition::Status(fRegistrationThread).c_str()));
        return;
    }
    if (routineSelector == 3)
    {
        MaintenanceHost host(fRegistrationThread);
        result.SetArgString(TXString(MaintenanceSnapshot(host).c_str()));
        return;
    }
    result.SetArgLong(static_cast<Sint32>(ArcAngles::Status::UnknownRoutine));
    if (routineSelector == 6)
    {
        result.SetArgLong(DocumentTransition::Revision(fRegistrationThread));
        return;
    }
    if (routineSelector == 7)
    {
        if (raw->args[0].argType != kStringArgType || raw->args[1].argType != kStringArgType
            || raw->args[2].argType != kStringArgType)
        {
            result.SetArgLong(-202);
            return;
        }
        const auto source = argTable.GetArgument(0).GetArgString();
        const auto target = argTable.GetArgument(1).GetArgString();
        const auto request = argTable.GetArgument(2).GetArgString();
        result.SetArgLong(DocumentTransition::Stage(fRegistrationThread,
            std::wstring(source.GetWCharPtr(), source.GetLength()),
            std::wstring(target.GetWCharPtr(), target.GetLength()),
            std::wstring(request.GetWCharPtr(), request.GetLength())));
        return;
    }
    if (routineSelector == 0)
    {
        result.SetArgLong(ArcAngles::kNativeRevision);
        return;
    }
    if (routineSelector == 2)
    {
        MaintenanceHost host(fRegistrationThread);
        try
        {
            result.SetArgLong(host.ContextReady() ? Maintenance::kRevision
                : static_cast<Sint32>(Maintenance::Status::InvalidContext));
        }
        catch (...) { result.SetArgLong(static_cast<Sint32>(Maintenance::Status::NativeException)); }
        return;
    }
    if (routineSelector == 4 || routineSelector == 5)
    {
        if (raw->args[0].argType != kStringArgType)
        {
            result.SetArgLong(static_cast<Sint32>(Maintenance::Status::InvalidArguments));
            return;
        }
        MaintenanceHost host(fRegistrationThread);
        const auto path = argTable.GetArgument(0).GetArgString();
        const auto status = Maintenance::Run(host, std::wstring(path.GetWCharPtr(), path.GetLength()),
                                             routineSelector == 4);
        result.SetArgLong(static_cast<Sint32>(status));
        return;
    }
    if (routineSelector != 1)
        return;

    // VWPluginLibraryArgument getters only assert their tags in release
    // builds. Validate the actual union tags before reading their payloads.
    if (!ArcAngles::ArgumentTypesMatch(raw->args[0].argType,
                                     raw->args[1].argType,
                                     raw->args[2].argType))
    {
        result.SetArgLong(static_cast<Sint32>(ArcAngles::Status::InvalidArguments));
        return;
    }

    ArcHost host(fRegistrationThread);
    const auto status = ArcAngles::SetAngles(host, argTable.GetArgument(0).GetArgHandle(),
                                            argTable.GetArgument(1).GetArgReal(),
                                            argTable.GetArgument(2).GetArgReal());
    result.SetArgLong(static_cast<Sint32>(status));
}
