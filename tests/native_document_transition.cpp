// Exercise real callbacks and deferred native adapter against independent SDK
// state. These tests never connect to or launch Vectorworks.
#include "../native/Source/Bridge/DocumentTransition.cpp"
#include "../native/Source/Bridge/BridgeVSFunctions.cpp"
#include <cassert>
#include <iostream>

using namespace VwxBridge;
namespace DT = VwxBridge::DocumentTransition;
const std::wstring SOURCE = L"C:\\Projects\\Kimberly 1027 N 390 E - 3D Model v2027.vwx";
const std::wstring TARGET = L"C:\\Projects\\Kimberly 1027 N 390 E - Native Editable R4.vwx";
const std::wstring ID(64, L'a');

void Reset()
{
    modelSDK = {}; gSDK = &modelSDK;
    gCBP = reinterpret_cast<CallBackPtr>(2);
    modelCurrentThread = modelFrameThread = 11;
    modelCurrentProcess = modelFrameProcess = 7;
    modelWindowValid = true; modelFrame = reinterpret_cast<HWND>(1);
    modelFrameQueries = modelArgumentReads = modelResultReads = 0;
    modelTargetDiskExists = true; modelTargetSetError = 0;
    modelSDK.documents[0].path = SOURCE;
    DT::state = {}; DT::brokerThread = 0;
}

void AddTarget(const std::wstring& path = TARGET)
{
    auto doc = ModelFile{}; doc.path = path; doc.active = false; doc.reference = 20;
    modelSDK.documents.push_back(doc);
}

Sint32 Stage(CBridgeVSRoutines& routines, const std::wstring& from = SOURCE,
             const std::wstring& to = TARGET, const std::wstring& request = ID)
{
    PluginLibraryArgTable raw;
    for (int i = 0; i < 3; ++i) raw.args[i].argType = kStringArgType;
    raw.args[0].stringValue.value = from;
    raw.args[1].stringValue.value = to;
    raw.args[2].stringValue.value = request;
    VWPluginLibraryArgTable args(&raw);
    routines.DispatchRoutine(7, args);
    assert(raw.functionResult.argType == kLongArgType);
    return raw.functionResult.longValue;
}

std::string Status(CBridgeVSRoutines& routines)
{
    PluginLibraryArgTable raw;
    VWPluginLibraryArgTable args(&raw);
    routines.DispatchRoutine(8, args);
    assert(raw.functionResult.argType == kStringArgType);
    std::string text;
    for (wchar_t c : raw.functionResult.stringValue.value) { assert(c < 128); text += static_cast<char>(c); }
    return text;
}

void NoMutations()
{
    assert(modelSDK.saveCalls == 0 && modelSDK.switchCalls == 0 && modelSDK.openCalls == 0
        && modelSDK.quitCalls == 0);
}

int main()
{
    Reset(); CBridgeVSRoutines routines;
    assert(DT::Revision(11) == 1);
    for (int i = 6; i <= 8; ++i)
    {
        assert(std::char_traits<char>::length(kFunctions[i].fName) <= 20);
        assert(kFunctions[i].fParams[i == 7 ? 4 : 1].fName == nullptr);
    }
    assert(Stage(routines) == -201); NoMutations(); // manual/unbound Python context
    std::cout << Status(routines) << '\n';

    for (int arg = 0; arg < 3; ++arg)
    for (short tag : {0, 3, 5, 16, 19, 25, 36})
    {
        Reset(); PluginLibraryArgTable raw;
        for (int i = 0; i < 3; ++i) raw.args[i].argType = kStringArgType;
        raw.args[arg].argType = tag;
        VWPluginLibraryArgTable args(&raw); routines.DispatchRoutine(7, args);
        assert(raw.functionResult.longValue == -202 && modelArgumentReads == 0);
        NoMutations();
    }
    for (int bad = 0; bad < 8; ++bad)
    {
        Reset(); assert(DT::BeginMenu(11, 1));
        if (bad == 0) modelCurrentThread = 12;
        if (bad == 1) modelFrameThread = 12;
        if (bad == 2) modelFrameProcess = 8;
        if (bad == 3) modelWindowValid = false;
        if (bad == 4) modelFrame = nullptr;
        if (bad == 5) gSDK = nullptr;
        if (bad == 6) gCBP = nullptr;
        if (bad == 7) DT::brokerThread = 12;
        assert(Stage(routines) == -201); NoMutations();
    }
    const std::wstring badPaths[] = {L"", L"test.vwx", L"C:test.vwx", L"\\test.vwx",
        L"C:\\test.txt", L"C:\\test.vwx:stream", L"C:\\*\\test.vwx", L"C:\\test.vwx ",
        L"C:\\test.vwx.", L"C:\\..\\test.vwx", L"\\\\?\\C:\\test.vwx", L"C:\\bad\xd800.vwx",
        std::wstring(L"C:\\test.vwx\0other", 17)};
    for (const auto& path : badPaths)
    {
        Reset(); assert(DT::BeginMenu(11, 1));
        assert(Stage(routines, path) == -202 && Stage(routines, SOURCE, path) == -202);
        assert(modelSDK.inventoryCalls == 0); NoMutations();
    }
    for (const auto& id : {std::wstring(), std::wstring(63, L'a'), std::wstring(65, L'a'),
                          std::wstring(64, L'A'), std::wstring(64, L'g')})
    {
        Reset(); assert(DT::BeginMenu(11, 1));
        assert(Stage(routines, SOURCE, TARGET, id) == -202); NoMutations();
    }
    Reset(); assert(DT::BeginMenu(11, 1));
    assert(Stage(routines, SOURCE, SOURCE) == -202); NoMutations();
    assert(Stage(routines, L"c:/projects/./Kimberly 1027 N 390 E - 3D Model v2027.vwx", SOURCE) == -202);

    for (int bad = 0; bad < 14; ++bad)
    {
        Reset(); assert(DT::BeginMenu(11, 1));
        if (bad == 0) modelSDK.documents.clear();
        if (bad == 1) modelSDK.documents[0].inMemory = true;
        if (bad == 2) modelSDK.documents[0].active = false;
        if (bad == 3) modelSDK.documents[0].reference = -1;
        if (bad == 4) { AddTarget(); modelSDK.documents[1].reference = 10; }
        if (bad == 5) AddTarget(SOURCE);
        if (bad == 6) { AddTarget(); modelSDK.documents[1].active = true; }
        if (bad == 7) modelSDK.workingFile = true;
        if (bad == 8) modelSDK.documents[0].exists = false;
        if (bad == 9) modelSDK.previouslySaved = false;
        if (bad == 10) modelSDK.activeUnavailable = true;
        if (bad == 11) modelSDK.documents[0].path = TARGET;
        if (bad == 12) modelSDK.nullIdentifier = true;
        if (bad == 13) { AddTarget(); modelSDK.documents[1].inMemory = true; }
        assert(Stage(routines) < 0 && DT::state.phase == DT::Phase::Failed);
        DT::EndMenu(1, true); NoMutations();
    }
    for (int bad = 0; bad < 2; ++bad)
    {
        Reset(); assert(DT::BeginMenu(11, 1));
        if (bad == 0) modelTargetDiskExists = false;
        else modelTargetSetError = 50;
        assert(Stage(routines) == -207); DT::EndMenu(1, true); NoMutations();
    }

    // All actions are deferred until the exact enclosing broker invocation
    // returns with an observed completion. Stale/nested tokens do nothing.
    Reset(); assert(DT::BeginMenu(11, 71));
    assert(!DT::BeginMenu(11, 72)); assert(Stage(routines) == 1);
    assert(Stage(routines) == -208); NoMutations();
    DT::EndMenu(72, true); NoMutations();
    assert(DT::state.phase == DT::Phase::Staged);
    DT::EndMenu(71, false); NoMutations();
    assert(DT::state.code == DT::Code::MenuUnconfirmed && DT::state.phase == DT::Phase::Failed);
    assert(DT::BeginMenu(11, 73)); assert(Stage(routines) == -209);
    DT::EndMenu(73, true); NoMutations();

    // Preserve source and every other open document. Exact SDK refs choose a
    // switch; the path's spaces/hyphens never enter a window-title parser.
    Reset(); AddTarget(); assert(DT::BeginMenu(11, 1)); assert(Stage(routines) == 1);
    NoMutations(); DT::EndMenu(1, true);
    assert(DT::state.phase == DT::Phase::Completed && DT::state.dispatched && DT::state.saveConfirmed);
    assert(modelSDK.saveCalls == 1 && modelSDK.switchCalls == 1 && modelSDK.openCalls == 0);
    assert(modelSDK.savedPath == SOURCE && modelSDK.switchedReference == 20);
    assert(modelSDK.documents.size() == 2 && !modelSDK.documents[0].active && modelSDK.documents[1].active);
    DT::EndMenu(1, true); assert(modelSDK.saveCalls == 1 && modelSDK.switchCalls == 1);
    assert(DT::BeginMenu(11, 2)); assert(Stage(routines, TARGET, SOURCE) == -209);
    DT::EndMenu(2, true);
    assert(DT::BeginMenu(11, 3)); assert(Stage(routines, TARGET, SOURCE, std::wstring(64, L'b')) == 1);
    DT::EndMenu(3, true);
    assert(modelSDK.saveCalls == 2 && modelSDK.switchCalls == 2 && modelSDK.openCalls == 0);

    Reset(); assert(DT::BeginMenu(11, 1)); assert(Stage(routines) == 1); DT::EndMenu(1, true);
    assert(DT::state.phase == DT::Phase::Completed);
    assert(modelSDK.saveCalls == 1 && modelSDK.openCalls == 1 && modelSDK.switchCalls == 0);
    assert(!modelSDK.lastShowErrorMessages && modelSDK.openedPath == TARGET);
    assert(modelSDK.documents.size() == 2 && modelSDK.documents[0].path == SOURCE);

    // Reordering an inventory is harmless; replacement or activation of a
    // different reference/path between stage and execution prevents saving.
    Reset(); AddTarget(); assert(DT::BeginMenu(11, 1)); assert(Stage(routines) == 1);
    std::swap(modelSDK.documents[0], modelSDK.documents[1]); DT::EndMenu(1, true);
    assert(DT::state.phase == DT::Phase::Completed && modelSDK.switchCalls == 1);
    for (int change = 0; change < 7; ++change)
    {
        Reset(); assert(DT::BeginMenu(11, 1)); assert(Stage(routines) == 1);
        if (change == 0) modelSDK.documents[0].reference = 99;
        if (change == 1) modelSDK.documents[0].path = TARGET;
        if (change == 2) modelSDK.documents.clear();
        if (change == 3) AddTarget();
        if (change == 4) modelSDK.workingFile = true;
        if (change == 5) modelTargetDiskExists = false;
        if (change == 6) modelCurrentThread = 12;
        DT::EndMenu(1, true); NoMutations(); assert(DT::state.phase == DT::Phase::Failed);
    }

    for (int bad = 0; bad < 8; ++bad)
    {
        Reset(); assert(DT::BeginMenu(11, 1)); assert(Stage(routines) == 1);
        if (bad == 0) modelSDK.saveError = 5;
        if (bad == 1) modelSDK.throwSave = true;
        if (bad == 2) modelSDK.onSave = [] { modelSDK.documents[0].reference = 99; };
        if (bad == 3) modelSDK.onSave = [] { gSDK = nullptr; };
        if (bad == 4) modelSDK.onSave = [] { AddTarget(); };
        if (bad == 5) modelSDK.onSave = [] { modelSDK.documents[0].active = false; };
        if (bad == 6) modelSDK.onSave = [] { modelSDK.workingFile = true; };
        if (bad == 7) modelSDK.onSave = [] { modelSDK.throwInventory = true; };
        DT::EndMenu(1, true);
        assert(DT::state.phase == DT::Phase::Uncertain && DT::state.dispatched);
        assert(modelSDK.saveCalls == 1 && modelSDK.switchCalls == 0 && modelSDK.openCalls == 0);
        gSDK = &modelSDK; DT::EndMenu(1, true); assert(modelSDK.saveCalls == 1);
        assert(DT::BeginMenu(11, 2));
        assert(Stage(routines, SOURCE, TARGET, std::wstring(64, L'b')) == -208);
        DT::EndMenu(2, true); assert(modelSDK.saveCalls == 1);
    }

    // False native return, exception, no-op, wrong active path and destructive
    // host callbacks remain uncertain. No opposite route or automatic replay.
    for (bool existing : {false, true})
    for (int bad = 0; bad < 5; ++bad)
    {
        Reset(); if (existing) AddTarget();
        assert(DT::BeginMenu(11, 1)); assert(Stage(routines) == 1);
        if (bad == 0) modelSDK.openReturns = modelSDK.switchReturns = false;
        if (bad == 1) modelSDK.throwOpen = modelSDK.throwSwitch = true;
        if (bad == 2) modelSDK.transitionNoOp = true;
        const auto corrupt = [bad] {
            if (bad == 3) modelSDK.documents.erase(modelSDK.documents.begin());
            if (bad == 4) for (auto& doc : modelSDK.documents) if (doc.active) doc.path = L"C:\\Wrong.vwx";
        };
        modelSDK.onOpen = modelSDK.onSwitch = corrupt;
        DT::EndMenu(1, true); DT::EndMenu(1, true);
        assert(DT::state.phase == DT::Phase::Uncertain && DT::state.transitionDispatched);
        assert(modelSDK.saveCalls == 1 && modelSDK.switchCalls == (existing ? 1 : 0)
            && modelSDK.openCalls == (existing ? 0 : 1));
    }

    Reset(); assert(DT::BeginMenu(11, 1)); assert(Stage(routines) == 1);
    modelSDK.onSave = [&] {
        assert(!DT::BeginMenu(11, 2));
        assert(Stage(routines) == -201);
        DT::EndMenu(1, true);
        assert(modelSDK.openCalls == 0);
    };
    DT::EndMenu(1, true); assert(DT::state.phase == DT::Phase::Completed && modelSDK.openCalls == 1);

    // UTF-16 escapes, not locale conversion or lossy title parsing, carry the
    // complete source/target paths into the independently parsed JSON record.
    Reset(); const std::wstring unicode = L"C:\\Projects\\caf\u00e9 \u6771\u4eac \xd83d\xde00 - house.vwx";
    assert(DT::BeginMenu(11, 1)); assert(Stage(routines, SOURCE, unicode) == 1);
    DT::EndMenu(1, true); assert(DT::state.phase == DT::Phase::Completed);
    std::cout << Status(routines) << '\n';
}
