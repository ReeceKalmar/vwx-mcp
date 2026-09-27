// Actual production dispatch against a stateful, independent document model.
#include "../native/Source/Bridge/DocumentTransition.cpp"
#include "../native/Source/Bridge/BridgeVSFunctions.cpp"
#include <cassert>
#include <iostream>

using namespace VwxBridge;

void ResetMaintenance()
{
    modelSDK = {};
    gSDK = &modelSDK;
    gCBP = reinterpret_cast<CallBackPtr>(2);
    modelCurrentThread = modelFrameThread = 11;
    modelCurrentProcess = modelFrameProcess = 7;
    modelWindowValid = true;
    modelFrame = reinterpret_cast<HWND>(1);
    modelFrameQueries = modelArgumentReads = modelResultReads = 0;
}

PluginLibraryArgTable MaintenanceArguments(const std::wstring& path = L"C:\\Projects\\Drawing.vwx")
{
    PluginLibraryArgTable raw;
    raw.args[0].argType = kStringArgType;
    raw.args[0].stringValue.value = path;
    return raw;
}

Sint32 Number(CBridgeVSRoutines& routines, Sint32 selector, PluginLibraryArgTable& raw)
{
    VWPluginLibraryArgTable table(&raw);
    routines.DispatchRoutine(selector, table);
    assert(raw.functionResult.argType == kLongArgType);
    return raw.functionResult.longValue;
}

std::string Snapshot(CBridgeVSRoutines& routines)
{
    PluginLibraryArgTable raw;
    VWPluginLibraryArgTable table(&raw);
    routines.DispatchRoutine(3, table);
    assert(raw.functionResult.argType == kStringArgType);
    std::string result;
    for (auto c : raw.functionResult.stringValue.value) { assert(c < 128); result += static_cast<char>(c); }
    return result;
}

int main()
{
    ResetMaintenance();
    CBridgeVSRoutines routines;
    auto raw = MaintenanceArguments();
    assert(Number(routines, 2, raw) == 1);
    assert(modelSDK.inventoryCalls == 0 && modelSDK.saveCalls == 0 && modelSDK.quitCalls == 0);
    for (int selector = 2; selector <= 5; ++selector)
    {
        assert(std::char_traits<char>::length(kFunctions[selector].fName) <= 20);
        assert(kFunctions[selector].fParams[selector < 4 ? 1 : 2].fName == nullptr);
    }

    // This output is independently parsed/compared by Python's JSON parser.
    modelSDK.documents[0].path = L"C:\\Projects\\caf\u00e9 \u6771\u4eac \xd83d\xde00.vwx";
    std::cout << Snapshot(routines) << '\n';
    assert(modelSDK.saveCalls == 0 && modelSDK.quitCalls == 0);
    modelSDK.documents[0].path = L"Untitled \"quote\"\tline\n";
    modelSDK.documents[0].inMemory = true;
    std::cout << Snapshot(routines) << '\n';
    modelCurrentThread = 15;
    std::cout << Snapshot(routines) << '\n';

    // Every maintenance entry point checks UI/SDK context, independently of
    // argument shape. Rejected context cannot enumerate, save or quit.
    for (int selector : {2, 3, 4, 5})
    {
        for (int invalid = 0; invalid < 7; ++invalid)
        {
            ResetMaintenance(); raw = MaintenanceArguments();
            if (invalid == 0) modelCurrentThread = 12;
            if (invalid == 1) modelFrameThread = 12;
            if (invalid == 2) modelFrameProcess = 8;
            if (invalid == 3) modelWindowValid = false;
            if (invalid == 4) modelFrame = nullptr;
            if (invalid == 5) gSDK = nullptr;
            if (invalid == 6) gCBP = nullptr;
            if (selector == 3) assert(Snapshot(routines).find("\"code\":-101") != std::string::npos);
            else assert(Number(routines, selector, raw) == -101);
            assert(modelSDK.inventoryCalls == 0 && modelSDK.saveCalls == 0 && modelSDK.quitCalls == 0);
        }
    }

    for (int selector : {4, 5})
    {
        for (short tag : {0, 1, 3, 5, 16, 19, 25, 36})
        {
            ResetMaintenance(); raw = MaintenanceArguments(); raw.args[0].argType = tag;
            assert(Number(routines, selector, raw) == -102);
            assert(modelArgumentReads == 0 && modelSDK.inventoryCalls == 0);
        }
        const std::wstring invalidPaths[] = {L"", L"Drawing.vwx", L"C:Drawing.vwx", L"\\Drawing.vwx",
            L"C:\\Projects\\Other.txt", L"C:\\Projects\\.vwx", L"C:\\Projects\\Drawing.vwx ",
            L"C:\\Projects\\Drawing.vwx.", L"C:\\Projects\\Drawing.vwx:stream", L"C:\\*\\Drawing.vwx",
            L"\\\\?\\C:\\Projects\\Drawing.vwx", L"\\\\.\\C:\\Projects\\Drawing.vwx",
            L"\\\\server\\Drawing.vwx", L"C:\\..\\Drawing.vwx", L"\\\\server\\share\\..\\Drawing.vwx",
            std::wstring(L"C:\\Projects\\Drawing.vwx\0trailer", 32), L"C:\\Projects\\\xd800.vwx"};
        for (const auto& path : invalidPaths)
        {
            ResetMaintenance(); raw = MaintenanceArguments(path);
            assert(Number(routines, selector, raw) == -102);
            assert(modelSDK.inventoryCalls == 0 && modelSDK.saveCalls == 0 && modelSDK.quitCalls == 0);
        }
        ResetMaintenance(); raw = MaintenanceArguments(L"C:\\Projects\\Other.vwx");
        assert(Number(routines, selector, raw) == -105);
        assert(modelSDK.saveCalls == 0 && modelSDK.quitCalls == 0);

        // Each distinct unsafe state is rejected, including any unrelated
        // additional document even when it is inactive and already saved.
        for (int unsafe = 0; unsafe < 12; ++unsafe)
        {
            ResetMaintenance(); raw = MaintenanceArguments();
            if (unsafe == 0) modelSDK.documents.clear();
            if (unsafe == 1) { auto second = ModelFile{}; second.reference = 11; second.active = false;
                               second.path = L"C:\\Other.vwx"; modelSDK.documents.push_back(second); }
            if (unsafe == 2) modelSDK.documents[0].inMemory = true;
            if (unsafe == 3) modelSDK.documents[0].active = false;
            if (unsafe == 4) modelSDK.documents[0].path += L"p";
            if (unsafe == 5) modelSDK.workingFile = true;
            if (unsafe == 6) modelSDK.documents[0].exists = false;
            if (unsafe == 7) modelSDK.previouslySaved = false;
            if (unsafe == 8) modelSDK.activeUnavailable = true;
            if (unsafe == 9) modelSDK.documents[0].pathError = 51;
            if (unsafe == 10) modelSDK.nullIdentifier = true;
            if (unsafe == 11) modelSDK.documents[0].existsError = 52;
            const auto status = Number(routines, selector, raw);
            assert(status < 0);
            if (unsafe == 5) assert(status == -106);
            if (unsafe == 9 || unsafe == 10) assert(status == -103);
            assert(modelSDK.saveCalls == 0 && modelSDK.quitCalls == 0);
        }

        // A different open-file reference is a new document instance even if
        // its visible path matches. No write/quit follows a changed preflight.
        ResetMaintenance(); raw = MaintenanceArguments();
        modelSDK.onInventory = [](int call) { if (call == 2) modelSDK.documents[0].reference = 44; };
        assert(Number(routines, selector, raw) == -108);
        assert(modelSDK.saveCalls == 0 && modelSDK.quitCalls == 0);
    }

    // Legal normalization cannot redirect the save to a different file.
    ResetMaintenance(); raw = MaintenanceArguments(L"c:/projects/./folder/../DRAWING.VWX");
    assert(Number(routines, 4, raw) == 1);
    assert(modelSDK.savedPath == L"C:\\Projects\\Drawing.vwx");
    assert(modelSDK.saveCalls == 1 && modelSDK.quitCalls == 0 && modelSDK.inventoryCalls == 3);
    ResetMaintenance();
    modelSDK.documents[0].path = L"\\\\server\\share\\caf\u00e9 \u6771\u4eac \xd83d\xde00.vwx";
    raw = MaintenanceArguments(L"//SERVER/share/CAF\u00c9 \u6771\u4eac \xd83d\xde00.VWX");
    assert(Number(routines, 4, raw) == 1 && modelSDK.saveCalls == 1);

    // Both entry points save exactly once. In particular, Quit cannot use a
    // prior menu job's save as evidence that it may omit its own current save.
    for (int selector : {4, 5})
    {
        // Nonzero GSError is failure even when the host changed data. A save
        // callback may alter identity; its zero return cannot hide that change.
        ResetMaintenance(); raw = MaintenanceArguments(); modelSDK.saveError = 0x03000005;
        assert(Number(routines, selector, raw) == -107 && modelSDK.saveCalls == 1 && modelSDK.quitCalls == 0);
        for (int change = 0; change < 9; ++change)
        {
            ResetMaintenance(); raw = MaintenanceArguments();
            modelSDK.onSave = [change]() {
                if (change == 0) modelSDK.documents.clear();
                if (change == 1) modelSDK.documents[0].reference = 99;
                if (change == 2) modelSDK.documents[0].path = L"C:\\Changed.vwx";
                if (change == 3) modelSDK.documents[0].inMemory = true;
                if (change == 4) { auto doc = ModelFile{}; doc.reference = 42; modelSDK.documents.push_back(doc); }
                if (change == 5) modelSDK.workingFile = true;
                if (change == 6) modelSDK.documents[0].exists = false;
                if (change == 7) modelSDK.documents[0].active = false;
                if (change == 8) modelSDK.previouslySaved = false;
            };
            assert(Number(routines, selector, raw) == -108 && modelSDK.saveCalls == 1 && modelSDK.quitCalls == 0);
        }
        ResetMaintenance(); raw = MaintenanceArguments(); modelSDK.throwSave = true;
        assert(Number(routines, selector, raw) == -109 && modelSDK.saveCalls == 1 && modelSDK.quitCalls == 0);
        ResetMaintenance(); raw = MaintenanceArguments(); modelSDK.throwInventory = true;
        assert(Number(routines, selector, raw) == -109 && modelSDK.saveCalls == 0 && modelSDK.quitCalls == 0);
        ResetMaintenance(); raw = MaintenanceArguments();
        modelSDK.onSave = []() { modelSDK.throwInventory = true; };
        assert(Number(routines, selector, raw) == -109 && modelSDK.saveCalls == 1 && modelSDK.quitCalls == 0);
        // Reentry can invalidate context during either save or its readback.
        // Stop before another SDK action, preserving an uncertain saved state.
        ResetMaintenance(); raw = MaintenanceArguments();
        modelSDK.onSave = []() { gSDK = nullptr; };
        assert(Number(routines, selector, raw) == -101 && modelSDK.saveCalls == 1 && modelSDK.quitCalls == 0);
        assert(modelSDK.inventoryCalls == 2);
        ResetMaintenance(); raw = MaintenanceArguments();
        modelSDK.onInventory = [](int call) { if (call == 3) modelFrameThread = 12; };
        assert(Number(routines, selector, raw) == -101 && modelSDK.saveCalls == 1 && modelSDK.quitCalls == 0);
    }

    ResetMaintenance(); raw = MaintenanceArguments();
    // Even after an independently confirmed save, quit must make a fresh save
    // in its own callback, inspect after that save, then request normal quit.
    assert(Number(routines, 4, raw) == 1);
    modelSDK.maintenanceEvents.clear();
    modelSDK.onSave = []() { assert(modelSDK.quitCalls == 0); };
    assert(Number(routines, 5, raw) == 1 && modelSDK.quitCalls == 1 && modelSDK.saveCalls == 2);
    const std::vector<std::string> quitOrder = {"inventory", "inventory", "save", "inventory", "quit"};
    assert(modelSDK.maintenanceEvents == quitOrder);
    assert(modelSDK.savedPath == L"C:\\Projects\\Drawing.vwx");
    assert(modelSDK.lastAskForSave && !modelSDK.lastRestart && modelSDK.inventoryCalls == 6);
    // Returning from quit means only a request was made. A prompt/cancel may
    // leave the model alive, and an exception does not trigger another quit.
    assert(modelSDK.documents.size() == 1);
    ResetMaintenance(); raw = MaintenanceArguments(); modelSDK.throwQuit = true;
    assert(Number(routines, 5, raw) == -109 && modelSDK.quitCalls == 1 && modelSDK.saveCalls == 1);
    assert(modelSDK.maintenanceEvents == quitOrder);
    assert(modelSDK.lastAskForSave && !modelSDK.lastRestart);

    ResetMaintenance(); modelSDK.documents.clear();
    assert(Snapshot(routines).find("\"count\":0") != std::string::npos);
    ResetMaintenance(); modelSDK.documents.push_back(ModelFile{});
    assert(Snapshot(routines).find("\"code\":-103") != std::string::npos); // duplicate references
    ResetMaintenance(); modelSDK.documents[0].reference = -1;
    assert(Snapshot(routines).find("\"code\":-103") != std::string::npos);
    ResetMaintenance(); modelSDK.documents.resize(257);
    assert(Snapshot(routines).find("\"code\":-103") != std::string::npos);
}
