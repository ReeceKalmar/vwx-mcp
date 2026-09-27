// Exercise the actual production callback with an independent SDK boundary.
#include "../native/Source/Bridge/DocumentTransition.cpp"
#include "../native/Source/Bridge/BridgeVSFunctions.cpp"
#include <cassert>
#include <cstring>
#include <limits>

using namespace VwxBridge;

void ResetModel()
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

PluginLibraryArgTable Arguments(ModelArc* arc, double start = 90, double sweep = 180)
{
    PluginLibraryArgTable table;
    table.args[0].argType = kHandleArgType; table.args[0].handleValue = arc;
    table.args[1].argType = kRealArgType; table.args[1].realValue = start;
    table.args[2].argType = kRealArgType; table.args[2].realValue = sweep;
    return table;
}

Sint32 Dispatch(CBridgeVSRoutines& routines, PluginLibraryArgTable& raw, Sint32 selector = 1)
{
    VWPluginLibraryArgTable table(&raw);
    routines.DispatchRoutine(selector, table);
    assert(raw.functionResult.argType == kLongArgType);
    return raw.functionResult.longValue;
}

int main()
{
    // Public metadata: exact ABI, sentinel and real arguments (not angle or
    // distance tags, which could introduce unit conversion).
    assert(std::strlen(kFunctions[0].fName) <= 20 && std::strlen(kFunctions[1].fName) <= 20);
    assert(std::strcmp(kFunctions[0].fName, "VWXBridgeRevision") == 0);
    assert(std::strcmp(kFunctions[1].fName, "VWXBridgeSetArc") == 0);
    assert(kFunctions[0].fParams[0].fType == 3);
    assert(kFunctions[1].fParams[0].fType == 25);
    assert(kFunctions[1].fParams[1].fType == 5 && kFunctions[1].fParams[2].fType == 5);
    assert(kFunctions[1].fParams[3].fType == 3 && !kFunctions[1].fParams[4].fName);
    assert(!kFunctions[9].fName);

    ResetModel();
    CBridgeVSRoutines routines;
    ModelArc arc, untouched;
    auto table = Arguments(&arc);
    assert(Dispatch(routines, table, 0) == 1);
    assert(modelArgumentReads == 0 && modelSDK.typeReads == 0 && modelSDK.setterCalls == 0);
    for (Sint32 selector : {9, 19, std::numeric_limits<Sint32>::max()})
        assert(Dispatch(routines, table, selector) == -5);
    assert(modelArgumentReads == 0 && modelSDK.setterCalls == 0);
    VWPluginLibraryArgTable missing(nullptr);
    const auto resultReads = modelResultReads;
    routines.DispatchRoutine(1, missing);
    routines.DispatchRoutine(-1, missing);
    routines.DispatchRoutine(-2, missing);
    assert(modelResultReads == resultReads);

    // Mis-tagged union values must never be read, including bools, integer
    // angles, angle/distance tags, handle-output tags, and uninitialized tags.
    for (int index = 0; index < 3; ++index)
    {
        for (short tag : {0, 1, 3, 5, 7, 8, 16, 18, 25, 26, 38})
        {
            ResetModel(); table = Arguments(&arc);
            const short expected = index == 0 ? 25 : 5;
            if (tag == expected) continue;
            table.args[index].argType = tag;
            assert(Dispatch(routines, table) == -2);
            assert(modelArgumentReads == 0 && modelFrameQueries == 0 && modelSDK.setterCalls == 0);
        }
    }

    for (double bad : {std::numeric_limits<double>::infinity(), -std::numeric_limits<double>::infinity(),
                       std::numeric_limits<double>::quiet_NaN()})
    {
        for (int index : {1, 2})
        {
            ResetModel(); table = Arguments(&arc); table.args[index].realValue = bad;
            assert(Dispatch(routines, table) == -2);
            assert(modelFrameQueries == 0 && modelSDK.typeReads == 0 && modelSDK.setterCalls == 0);
        }
    }
    ResetModel(); table = Arguments(nullptr);
    assert(Dispatch(routines, table) == -2 && modelFrameQueries == 0);

    // Context checks independently reject registration-thread changes, an
    // authoritative frame owned by another thread/process, dead/null frames,
    // and missing SDK callbacks. No object lookup or setter follows rejection.
    for (int invalid = 0; invalid < 7; ++invalid)
    {
        ResetModel(); table = Arguments(&arc);
        if (invalid == 0) modelCurrentThread = 12;
        if (invalid == 1) modelFrameThread = 12;
        if (invalid == 2) modelFrameProcess = 8;
        if (invalid == 3) modelWindowValid = false;
        if (invalid == 4) modelFrame = nullptr;
        if (invalid == 5) gSDK = nullptr;
        if (invalid == 6) gCBP = nullptr;
        assert(Dispatch(routines, table) == -1);
        assert(modelSDK.typeReads == 0 && modelSDK.setterCalls == 0);
        if (invalid == 0 || invalid == 5 || invalid == 6) assert(modelFrameQueries == 0);
    }

    for (short type : {0, 3, 10, 16, 89, 111, -1})
    {
        ResetModel(); arc.type = type; table = Arguments(&arc);
        assert(Dispatch(routines, table) == -3);
        assert(modelSDK.typeReads == 1 && modelSDK.setterCalls == 0);
    }
    arc.type = 6;

    // Degree values and target identity reach the SDK exactly once. This
    // includes negative sweeps, zero and wrapped/large finite start angles;
    // this helper does not invent undocumented angular clamping.
    for (double start : {-720.0, -90.0, 0.0, 90.0, 360.0, 810.0})
    {
        for (double sweep : {-360.0, -90.0, 0.0, 180.0, 360.0})
        {
            ResetModel(); arc = ModelArc{}; table = Arguments(&arc, start, sweep);
            assert(Dispatch(routines, table) == 1);
            assert(modelSDK.setterCalls == 1 && modelSDK.lastHandle == &arc);
            assert(modelSDK.lastStart == start && modelSDK.lastSweep == sweep);
            assert(arc.start == start && arc.sweep == sweep);
            assert(arc.identity == 401 && arc.attributes == 73 && arc.parent == 19);
            assert(arc.x == 320 && arc.y == -260 && arc.rx == 10 && arc.ry == 10);
            assert(untouched.start == 0 && untouched.sweep == 90);
        }
    }

    // Exceptions before and after mutation stay uncertain, never trigger a
    // second setter, rollback or replacement object.
    for (int phase : {1, 2, 3})
    {
        ResetModel(); arc = ModelArc{}; modelSDK.throwPhase = phase; table = Arguments(&arc);
        assert(Dispatch(routines, table) == -4);
        assert(modelSDK.setterCalls == (phase == 1 ? 0 : 1));
        assert(arc.identity == 401 && arc.attributes == 73);
        assert(arc.start == (phase == 3 ? 90 : 0));
    }
    ResetModel(); arc = ModelArc{}; modelSDK.throwPhase = 4; table = Arguments(&arc);
    assert(Dispatch(routines, table) == 1 && arc.start == 0 && arc.sweep == 90);
    // Accepted deliberately cannot turn a silent host no-op into evidence.
    assert(modelSDK.setterCalls == 1);
}
