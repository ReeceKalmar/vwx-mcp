// Minimal independent SDK/Windows boundary model for compiling the production
// scripting callback offline. This does not emulate Vectorworks arc geometry.
#pragma once
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>
#include <functional>

using Sint32 = std::int32_t;
using DWORD = std::uint32_t;
using CallBackPtr = void*;
using HWND = void*;

struct ModelArc
{
    short type = 6;
    double start = 0, sweep = 90, x = 320, y = -260, rx = 10, ry = 10;
    int identity = 401, attributes = 73, parent = 19;
};
using MCObjectHandle = ModelArc*;

inline constexpr short kLongArgType = 3, kRealArgType = 5, kHandleArgType = 25, kStringArgType = 18;
inline constexpr short kArcNode = 6, kVLIBScopeUniversal = 0;
inline constexpr int kVCOMError_NoError = 0, noError = 0, TRUE = 1, CSTR_EQUAL = 2;

class TXString
{
public:
    TXString() = default;
    explicit TXString(const wchar_t* text) : value(text) {}
    explicit TXString(const char* ascii) { while (*ascii) value += static_cast<unsigned char>(*ascii++); }
    const wchar_t* GetWCharPtr() const { return value.c_str(); }
    size_t GetLength() const { return value.size(); }
    std::wstring value;
};

// Use the real, pure ordinal text-comparison API. No window/host operation is
// called through this declaration; all application/thread APIs remain modeled.
extern "C" __declspec(dllimport) int __stdcall CompareStringOrdinal(const wchar_t*, int, const wchar_t*, int, int);

struct ModelFile
{
    std::wstring path = L"C:\\Projects\\Drawing.vwx";
    Sint32 reference = 10;
    bool active = true, inMemory = false, exists = true;
    int pathError = 0, existsError = 0;
    int GetFileFullPath(TXString& text) { text.value = path; return pathError; }
    int ExistsOnDisk(bool& present) { present = exists; return existsError; }
};

namespace VectorWorks::Filing
{
    using IFileIdentifier = ModelFile;
    class IFileIdentifierPtr
    {
    public:
        IFileIdentifierPtr() = default;
        IFileIdentifierPtr(ModelFile* value) : pointer(value) {}
        void Release() { pointer = nullptr; }
        operator ModelFile*() const { return pointer; }
        ModelFile* operator->() const { return pointer; }
        ModelFile** operator&() { return &pointer; }
    private:
        ModelFile* pointer = nullptr;
    };
}
namespace VectorWorks
{
    struct SOpenFileInformation
    {
        Filing::IFileIdentifierPtr fpFileID;
        Sint32 fFileRef;
        bool fIsActive, fIsInMemoryOnly;
    };
    struct TVWArray_OpenFileInformation
    {
        std::vector<SOpenFileInformation> entries;
        size_t GetSize() const { return entries.size(); }
        const SOpenFileInformation& operator[](size_t index) const { return entries[index]; }
    };
}

struct PluginLibraryArg
{
    short argType = 0;
    MCObjectHandle handleValue = nullptr;
    double realValue = 0;
    Sint32 longValue = 0;
    TXString stringValue;
};
struct PluginLibraryArgTable
{
    PluginLibraryArg args[11];
    PluginLibraryArg functionResult;
};

inline DWORD modelCurrentThread = 11, modelFrameThread = 11;
inline DWORD modelCurrentProcess = 7, modelFrameProcess = 7;
inline bool modelWindowValid = true;
inline HWND modelFrame = reinterpret_cast<HWND>(1);
inline int modelFrameQueries = 0, modelArgumentReads = 0, modelResultReads = 0;
inline CallBackPtr gCBP = reinterpret_cast<CallBackPtr>(2);

inline DWORD GetCurrentThreadId() { return modelCurrentThread; }
inline DWORD GetCurrentProcessId() { return modelCurrentProcess; }
inline bool IsWindow(HWND frame) { return frame && modelWindowValid; }
inline DWORD GetWindowThreadProcessId(HWND, DWORD* process)
{
    *process = modelFrameProcess;
    return modelFrameThread;
}
inline HWND GS_GetMainHWND(CallBackPtr) { ++modelFrameQueries; return modelFrame; }

struct ModelSDK
{
    int typeReads = 0, setterCalls = 0, throwPhase = 0;
    MCObjectHandle lastHandle = nullptr;
    double lastStart = 0, lastSweep = 0;
    std::vector<ModelFile> documents = {ModelFile{}};
    int inventoryCalls = 0, activeCalls = 0, saveCalls = 0, quitCalls = 0, saveError = 0;
    bool workingFile = false, previouslySaved = true, activeUnavailable = false, nullIdentifier = false;
    bool throwInventory = false, throwSave = false, throwQuit = false;
    bool lastAskForSave = false, lastRestart = true;
    std::wstring savedPath;
    std::vector<std::string> maintenanceEvents;
    std::function<void(int)> onInventory;
    std::function<void()> onSave;
    short GetObjectTypeN(MCObjectHandle handle)
    {
        ++typeReads;
        if (throwPhase == 1) throw std::runtime_error("type read failed");
        return handle->type;
    }
    void GetOpenFilesList(VectorWorks::TVWArray_OpenFileInformation& output)
    {
        maintenanceEvents.push_back("inventory");
        ++inventoryCalls;
        if (throwInventory) throw std::runtime_error("inventory unavailable");
        if (onInventory) onInventory(inventoryCalls);
        for (auto& doc : documents)
            output.entries.push_back({nullIdentifier ? nullptr : &doc, doc.reference, doc.active, doc.inMemory});
    }
    bool IsAWorkingFile() { return workingFile; }
    bool GetActiveDocument(ModelFile** result, bool& saved)
    {
        ++activeCalls; saved = previouslySaved;
        if (activeUnavailable) return false;
        for (auto& doc : documents) if (doc.active) { *result = &doc; return true; }
        return false;
    }
    int SaveActiveDocumentPath(ModelFile* file)
    {
        maintenanceEvents.push_back("save");
        ++saveCalls; savedPath = file->path;
        if (onSave) onSave();
        if (throwSave) throw std::runtime_error("save outcome unknown");
        return saveError;
    }
    void CloseAllFilesAndQuitVectorworks(bool ask, bool restart)
    {
        maintenanceEvents.push_back("quit");
        ++quitCalls; lastAskForSave = ask; lastRestart = restart;
        if (throwQuit) throw std::runtime_error("quit outcome unknown");
    }
};
inline ModelSDK modelSDK;
inline ModelSDK* gSDK = &modelSDK;

inline void GS_SetArcAnglesN(CallBackPtr, MCObjectHandle handle, double start, double sweep)
{
    ++modelSDK.setterCalls;
    modelSDK.lastHandle = handle;
    modelSDK.lastStart = start;
    modelSDK.lastSweep = sweep;
    if (modelSDK.throwPhase == 2) throw std::runtime_error("before mutation");
    if (modelSDK.throwPhase != 4) { handle->start = start; handle->sweep = sweep; }
    if (modelSDK.throwPhase == 3) throw std::runtime_error("after mutation");
}

namespace VWFC::PluginSupport
{
    struct SFunctionParamDef { const char* fName; short fType; };
    struct SFunctionDef
    {
        const char* fName;
        const char* fCategory;
        const char* fDescription;
        Sint32 fVersion;
        signed char fScope;
        bool fHasReturnValue;
        SFunctionParamDef fParams[11];
    };
    class VWExtensionVSFunctions
    {
    public:
        VWExtensionVSFunctions(CallBackPtr, const SFunctionDef*) {}
        virtual ~VWExtensionVSFunctions() = default;
    };
    class Argument
    {
    public:
        PluginLibraryArg* item = nullptr;
        MCObjectHandle GetArgHandle() { ++modelArgumentReads; return item->handleValue; }
        double GetArgReal() { ++modelArgumentReads; return item->realValue; }
        TXString GetArgString() { ++modelArgumentReads; return item->stringValue; }
        void SetArgLong(Sint32 value) { item->argType = kLongArgType; item->longValue = value; }
        void SetArgString(const TXString& value) { item->argType = kStringArgType; item->stringValue = value; }
    };
    class VWPluginLibraryArgTable
    {
    public:
        explicit VWPluginLibraryArgTable(PluginLibraryArgTable* table) : raw(table) {}
        operator PluginLibraryArgTable*() { return raw; }
        Argument& GetResult() { ++modelResultReads; result.item = &raw->functionResult; return result; }
        Argument& GetArgument(unsigned index) { arguments[index].item = &raw->args[index]; return arguments[index]; }
    private:
        PluginLibraryArgTable* raw;
        Argument result, arguments[11];
    };
    class VWPluginLibraryRoutine { public: virtual ~VWPluginLibraryRoutine() = default; };
}

#define DEFINE_VWVSFunctions
#define BEGIN_VWVSFunctions(...)
#define ADD_VWVSFunctions_ROUTINE(...)
#define END_VWVSFunctions
#define DEFINE_LIB_DISPATCH_MAP virtual void DispatchRoutine(Sint32 routineSelector, VWPluginLibraryArgTable& argTable)
