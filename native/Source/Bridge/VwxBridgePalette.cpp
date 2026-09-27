#include "StdAfx.h"

#include "VwxBridgePalette.h"
#include "PumpScheduleState.h"
#include "AtomicStatusFile.h"


#include <cstdio>
#include <ctime>
#include <cctype>
#include <string>
#include <vector>
#include <algorithm>
#include <functional>

using namespace VwxBridge;

// All jobs run in the Python menu-command runner, one invocation per job.
// The palette only schedules the runner. No Python executes in notifications,
// web callbacks or timers. A private UI event invokes the documented SDK named
// menu route; only the host establishes the Python menu-command context.
// Deferred PIO resets need a return to the host loop.
// This limits context-related risks but cannot prevent invalid native API calls.
// Adaptive drain cadence. Job arrival is bursty — idle for minutes, then a
// dozen calls back to back — so a single flat period is either wasteful when
// nothing is queued or slow when something is. Run hot while the queue has
// work, fall back to the idle period after a quiet spell. kTrigDebounceMs is
// an exact multiple of kTickHotMs so the debounce never rejects a whole tick
// (see TriggerPump).
static const UINT    kTickHotMs      = 20;
static const UINT    kTickIdleMs     = 150;
static const DWORD   kTrigDebounceMs = 40;
static const DWORD   kCooldownMs     = 1500;
// Heartbeat writes are throttled independently of the queue polling cadence.
static const DWORD   kAliveEveryMs   = 250;
static UINT_PTR      gPumpTimer     = 0;
static UINT          gTickPeriod    = kTickIdleMs;
static DWORD         gLastBusyTick  = 0;
static DWORD         gLastAlive     = 0;
static bool          gPaused        = false;
static int           gLastQueue     = 0;
static DWORD         gLastTrigTick  = 0;
static HWND          gVwMainWnd     = nullptr;
static int           gDispatchCount = 0;        // manual native status-probe invocations
static PumpScheduleState gSchedule;
static const char*   gTriggerState = "idle";
static DWORD         gTriggerError = 0;
static unsigned long long gTriggerFailures = 0;
static unsigned long long gRunnerStamp = 0;
static unsigned long long gCompletionStamp = 0;
static bool          gTimerCallbackActive = false;
static HWND          gMenuBrokerWindow = nullptr;
static DWORD         gHostUiThread = 0;
static MenuBrokerState gMenuBroker;
static unsigned long long gPostedRunnerStamp = 0;
static unsigned long long gMenuInvocations = 0;
static unsigned long long gMenuReturns = 0;
static unsigned long long gBrokerRejections = 0;
static short         gLastMenuReturn = 0;
static bool          gHasMenuReturn = false;
static constexpr UINT kInvokeNamedMenuMessage = WM_APP + 0x27B;

static nlohmann::json SchedulerStatus();
static void WriteSchedulerStatus(const TXString& pluginDir);

// --------------------------------------------------------------------------------------------------------
// Helpers: VW-MCP plugin folder (job queue home) + job counting via Win32.

// Every layer resolves the same complete installation, canonical name first.
static bool IsPluginDir(const TXString& dir)
{
    for ( const wchar_t* name : { L"\\vwx_pump.py", L"\\commands.py" } ) {
        TXString path = dir;
        path << name;
        DWORD attrs = GetFileAttributesW( path.GetWCharPtr() );
        if ( attrs == INVALID_FILE_ATTRIBUTES || (attrs & FILE_ATTRIBUTE_DIRECTORY) )
            return false;
    }
    return true;
}

static TXString VwxPluginDir()
{
    static TXString cached;
    if ( !cached.IsEmpty() )
        return cached;

    const std::wstring hostYear = std::to_wstring(SDK_VERSION / 100 + 1995);
    if ( const wchar_t* forcedYear = _wgetenv(L"VWX_VW_VERSION") ) {
        if ( hostYear != forcedYear ) return "";
    }
    if ( const wchar_t* forced = _wgetenv(L"VWX_PLUGIN_DIR"); forced && *forced ) {
        TXString dir(forced);
        if ( IsPluginDir(dir) ) cached = dir;
        return cached; // An invalid explicit path must never fall back elsewhere.
    }
    const wchar_t* appdata = _wgetenv(L"APPDATA");
    if ( appdata == nullptr )
        return "";
    for ( const wchar_t* name : { L"VWX-MCP", L"VW-MCP" } ) {
        TXString dir;
        dir << appdata << L"\\Nemetschek\\Vectorworks\\" << hostYear.c_str()
            << L"\\Plug-ins\\" << name;
        if ( IsPluginDir(dir) ) {
            cached = dir;
            return cached;
        }
    }
    return "";
}

static int CountJobs(const TXString& pluginDir)
{
	if ( pluginDir.IsEmpty() )
		return -1;
	TXString pattern;
	pattern << pluginDir << "\\ipc\\jobs\\*.json";
	WIN32_FIND_DATAW findData;
	HANDLE h = FindFirstFileW( pattern.GetWCharPtr(), &findData );
	if ( h == INVALID_HANDLE_VALUE )
		return 0;
	int n = 0;
	do {
		if ( !(findData.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) )
			n++;
	} while ( FindNextFileW( h, &findData ) );
	FindClose( h );
	return n;
}

// Bridge status for the file-transport server.
// native.alive = "<epoch> <paused 0|1>"; stale/missing means palette closed.
static void WriteAlive(const TXString& pluginDir)
{
	if ( pluginDir.IsEmpty() )
		return;
	TXString path;
	path << pluginDir << "\\ipc\\native.alive";
	const std::string data = std::to_string(static_cast<long long>(time(nullptr)))
	    + (gPaused ? " 1" : " 0");
	WriteAtomicStatusFile(path.GetWCharPtr(), data);
	WriteSchedulerStatus(pluginDir);
}

// On palette close, remove the heartbeat immediately so external status
// tooling sees the bridge as off at once (don't wait for staleness).
static void RemoveAlive(const TXString& pluginDir)
{
	if ( pluginDir.IsEmpty() )
		return;
	TXString path;
	path << pluginDir << "\\ipc\\native.alive";
	_wremove( path.GetWCharPtr() );
}

// Diagnostic trace into bridge.log (shared with the Python pump).
static void LogLine(const char* msg)
{
	TXString pluginDir = VwxPluginDir();
	if ( pluginDir.IsEmpty() )
		return;
	TXString path;
	path << pluginDir << "\\bridge.log";
	FILE* f = _wfopen( path.GetWCharPtr(), L"a" );
	if ( f ) {
		time_t t = time(nullptr);
		struct tm tmv;
		localtime_s( &tmv, &t );
		fprintf( f, "[%02d:%02d:%02d] native: %s\n", tmv.tm_hour, tmv.tm_min, tmv.tm_sec, msg );
		fclose( f );
	}
}

// The entry and completion stamps have separate meanings. Only a completed
// outer invocation releases an outstanding trigger; neither proves job success.
static unsigned long long ReadRunnerStamp(const TXString& pluginDir, const char* filename)
{
    TXString path;
    path << pluginDir << "\\ipc\\" << filename;
    WIN32_FILE_ATTRIBUTE_DATA data;
    if (pluginDir.IsEmpty() || !GetFileAttributesExW(path.GetWCharPtr(), GetFileExInfoStandard, &data))
        return 0;
    return (static_cast<unsigned long long>(data.ftLastWriteTime.dwHighDateTime) << 32)
         | data.ftLastWriteTime.dwLowDateTime;
}

static nlohmann::json SchedulerStatus()
{
    nlohmann::json status;
    status["schema_version"] = 1;
    status["scheduler"] = "sdk-named-menu-broker-ack-v4";
    status["sdk_version"] = SDK_VERSION;
    status["updated_epoch"] = static_cast<long long>(time(nullptr));
    status["process_id"] = GetCurrentProcessId();
    status["timer_active"] = gPumpTimer != 0;
    status["paused"] = gPaused;
    status["queued_jobs"] = gLastQueue;
    status["last_trigger_state"] = gTriggerState;
    status["last_win32_error"] = gTriggerError;
    status["trigger_failures"] = gTriggerFailures;
    status["posts"] = gSchedule.posted;
    status["foreground_posts"] = gSchedule.foregroundPosts;
    status["background_posts"] = gSchedule.backgroundPosts;
    status["runner_completions_observed"] = gSchedule.acknowledged;
    status["pending"] = gSchedule.pending;
    status["pending_age_ms"] = gSchedule.pending ? GetTickCount64() - gSchedule.postedAt : 0;
    status["acknowledgment_timeouts"] = gSchedule.timeouts;
    status["runner_stamp"] = gRunnerStamp;
    status["completion_stamp"] = gCompletionStamp;
    status["keyboard_state_modified"] = false;
    status["modifiers_pending_restore"] = false; // Compatibility; no keyboard state is modified.
    status["frame_source"] = "GS_GetMainHWND";
    status["frame_available"] = gVwMainWnd != nullptr && IsWindow(gVwMainWnd);
    status["frame_has_win32_menu"] = gVwMainWnd != nullptr && GetMenu(gVwMainWnd) != nullptr;
    status["broker_window_available"] = gMenuBrokerWindow != nullptr && IsWindow(gMenuBrokerWindow);
    status["broker_message_pending"] = gMenuBroker.queuedToken != 0;
    status["menu_invocation_active"] = gMenuBroker.active;
    status["menu_invocations"] = gMenuInvocations;
    status["menu_returns"] = gMenuReturns;
    status["broker_rejections"] = gBrokerRejections;
    status["menu_return_available"] = gHasMenuReturn;
    if (gHasMenuReturn) status["last_menu_return"] = gLastMenuReturn;
    status["menu_caption"] = "VWX Bridge Start";
    status["global_input"] = false;
    status["focus_changed_by_bridge"] = false;
    status["evidence_scope"] = "Posting and outer menu-invocation completion; not job success or native semantics";
    return status;
}

static void WriteSchedulerStatus(const TXString& pluginDir)
{
    if (pluginDir.IsEmpty()) return;
    TXString path;
    path << pluginDir << "\\ipc\\native.scheduler.json";
    WriteAtomicStatusFile(path.GetWCharPtr(), SchedulerStatus().dump());
}

// --------------------------------------------------------------------------------------------------------
// GS_GetMainHWND is the SDK's authoritative MFC application-frame accessor.
// Capture it during palette initialization, not a timer, and never guess by
// title. A floating/custom menu bar need not expose a Win32 HMENU at this HWND.
static bool ModalDialogOpen();
static LRESULT CALLBACK MenuBrokerWindowProc(HWND wnd, UINT message, WPARAM token, LPARAM unused);

static bool BackgroundInvocationAllowed()
{
    if (gPumpTimer == 0 || gPaused) {
        gTriggerState = gPaused ? "paused_before_menu_invocation" : "stopped_before_menu_invocation";
        return false;
    }
    HWND wnd = gVwMainWnd;
    if (wnd == nullptr || !IsWindow(wnd)) {
        gTriggerState = "no_vectorworks_frame";
        return false;
    }
    DWORD processId = 0;
    const DWORD threadId = GetWindowThreadProcessId(wnd, &processId);
    if (processId != GetCurrentProcessId() || threadId != gHostUiThread || threadId != GetCurrentThreadId()) {
        gTriggerState = "target_ownership_changed";
        return false;
    }
    if (!IsWindowVisible(wnd) || IsIconic(wnd) || !IsWindowEnabled(wnd)) {
        gTriggerState = !IsWindowVisible(wnd) ? "target_hidden" : IsIconic(wnd) ? "target_minimized" : "target_disabled";
        return false;
    }
    if (ModalDialogOpen()) {
        gTriggerState = "modal_dialog_open";
        return false;
    }
    GUITHREADINFO threadInfo = {};
    threadInfo.cbSize = sizeof(threadInfo);
    if (!GetGUIThreadInfo(threadId, &threadInfo)) {
        gTriggerState = "ui_thread_state_unavailable";
        gTriggerError = GetLastError();
        ++gTriggerFailures;
        return false;
    }
    if (threadInfo.flags & (GUI_INMENUMODE | GUI_SYSTEMMENUMODE | GUI_POPUPMENUMODE | GUI_INMOVESIZE)) {
        gTriggerState = "ui_thread_interactive_loop";
        return false;
    }
    if (gSDK == nullptr) {
        gTriggerState = "sdk_unavailable";
        return false;
    }
    return true;
}

static bool InitializeMenuBroker()
{
    gVwMainWnd = GS_GetMainHWND(gCBP);
    DWORD processId = 0;
    gHostUiThread = gVwMainWnd ? GetWindowThreadProcessId(gVwMainWnd, &processId) : 0;
    if (processId != GetCurrentProcessId() || gHostUiThread != GetCurrentThreadId()) {
        gTriggerState = "sdk_frame_ownership_invalid";
        return false;
    }
    if (gMenuBrokerWindow != nullptr && IsWindow(gMenuBrokerWindow)) return true;
    HMODULE module = nullptr;
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           reinterpret_cast<LPCWSTR>(&MenuBrokerWindowProc), &module)) return false;
    const wchar_t* className = L"VwxBridge.MenuRunnerBroker.v4";
    WNDCLASSW windowClass = {};
    windowClass.lpfnWndProc = MenuBrokerWindowProc;
    windowClass.hInstance = module;
    windowClass.lpszClassName = className;
    if (!RegisterClassW(&windowClass)) {
        WNDCLASSW existing = {};
        if (GetLastError() != ERROR_CLASS_ALREADY_EXISTS
            || !GetClassInfoW(module, className, &existing)
            || existing.lpfnWndProc != MenuBrokerWindowProc || existing.hInstance != module) return false;
    }
    gMenuBrokerWindow = CreateWindowExW(0, className, L"", 0, 0, 0, 0, 0,
                                       HWND_MESSAGE, nullptr, module, nullptr);
    return gMenuBrokerWindow != nullptr;
}

static bool PostBackgroundMenuCommand()
{
    if (!gMenuBroker.CanQueue() || gMenuBrokerWindow == nullptr || !IsWindow(gMenuBrokerWindow)) {
        gTriggerState = "menu_broker_unavailable_or_busy";
        return false;
    }
    if (!BackgroundInvocationAllowed()) return false;
    const TXString pluginDir = VwxPluginDir();
    gRunnerStamp = ReadRunnerStamp(pluginDir, "pump.stamp");
    gCompletionStamp = ReadRunnerStamp(pluginDir, "pump.complete.stamp");
    if (RunnerMayBeActive(gRunnerStamp, gCompletionStamp)) {
        gTriggerState = "outer_runner_still_active";
        return false;
    }
    gPostedRunnerStamp = gRunnerStamp;
    const auto token = gMenuBroker.Reserve();
    // The timer posts only a private event. The SDK menu call occurs later in
    // an ordinary UI-thread window event, outside timers/CEF/notifications.
    if (!PostMessageW(gMenuBrokerWindow, kInvokeNamedMenuMessage, static_cast<WPARAM>(token), 0)) {
        gMenuBroker.PostFailed(token); // No message was queued; no host call occurred.
        gTriggerState = "post_menu_broker_failed";
        gTriggerError = GetLastError();
        ++gTriggerFailures;
        return false;
    }
    gTriggerState = "posted_waiting_for_completion";
    gTriggerError = 0;
    return true;
}

static LRESULT CALLBACK MenuBrokerWindowProc(HWND wnd, UINT message, WPARAM token, LPARAM unused)
{
    if (message != kInvokeNamedMenuMessage) return DefWindowProcW(wnd, message, token, unused);
    if (wnd != gMenuBrokerWindow || unused != 0 || GetCurrentThreadId() != gHostUiThread
        || !gMenuBroker.BeginDelivery(static_cast<MenuBrokerState::Token>(token))) return 0;
    struct DeliveryGuard {
        ~DeliveryGuard() { gMenuBroker.EndDelivery(); }
    } deliveryGuard;
    // This token is already consumed. A rejection holds the outstanding
    // completion fence and never automatically reschedules an unknown call.
    const auto reject = [](const char* reason) {
        if (reason) gTriggerState = reason;
        ++gBrokerRejections;
        ++gTriggerFailures;
    };
    if (gTimerCallbackActive || !gSchedule.pending) {
        reject("menu_broker_context_changed");
        return 0;
    }
    if (!BackgroundInvocationAllowed()) { reject(nullptr); return 0; }
    const TXString pluginDir = VwxPluginDir();
    gLastQueue = CountJobs(pluginDir);
    gRunnerStamp = ReadRunnerStamp(pluginDir, "pump.stamp");
    gCompletionStamp = ReadRunnerStamp(pluginDir, "pump.complete.stamp");
    if (gLastQueue <= 0) { reject("menu_broker_queue_empty"); return 0; }
    if (gRunnerStamp != gPostedRunnerStamp || gCompletionStamp != gSchedule.stampBefore
        || RunnerMayBeActive(gRunnerStamp, gCompletionStamp)) {
        reject("menu_broker_runner_changed");
        return 0;
    }
    ++gMenuInvocations;
    gHasMenuReturn = false;
    gTriggerState = "sdk_named_menu_invoking";
    try {
        // SDK 3200 APIBase.Legacy.Defs.h:6639 documents external menu-file
        // names, chunkIndex=0 and recursive invocation. The installed file is
        // "VWX Bridge Start.vsm". The host creates its Python menu context;
        // this plugin never calls a Python/script engine. Live safety remains
        // to be verified. The selector is resolved by the host each invocation,
        // and does not make workspace/document changes transactional.
        gLastMenuReturn = gSDK->DoMenuName("VWX Bridge Start", 0);
        gHasMenuReturn = true;
        ++gMenuReturns;
        gTriggerState = "sdk_named_menu_returned_waiting_for_completion";
    }
    catch (...) {
        // Do not unwind through Win32 or replay an uncertain native call.
        ++gTriggerFailures;
        gTriggerState = "sdk_named_menu_exception_uncertain";
        LogLine("SDK named-menu invocation threw; holding without replay");
    }
    // The SDK return is diagnostic only. A later timer observes the real
    // pump.complete.stamp, after this entire synchronous menu call returns.
    return 0;
}
// Fire triggers. Called from the heartbeat timer when jobs are queued.
static void TriggerPump()
{
	DWORD now = GetTickCount();
	// Debounce must divide evenly into the timer period, or the two beat
	// against each other: a 120ms guard on a 100ms tick meant every second
	// tick was rejected and the real trigger cadence was 200ms, not the
	// intended 100ms — the single largest term in the per-call latency floor.
	// kTrigDebounceMs is an exact multiple of kTickHotMs.
	if ( now - gLastTrigTick < kTrigDebounceMs )
		return;
	if (!gSchedule.CanPost()) {
		gTriggerState = gSchedule.timedOut ? "runner_completion_timeout" : "posted_waiting_for_completion";
		return;
	}
	if ( ModalDialogOpen() ) {
		gTriggerState = "modal_dialog_open";
		return;                                  // a real modal is up — hold
	}
	gLastTrigTick = now;

	// Every job reaches the Python menu-command runner via a targeted message.
	// Foreground state is recorded only; it never selects a different path.
	DWORD foregroundProcess = 0;
	GetWindowThreadProcessId(GetForegroundWindow(), &foregroundProcess);
	if (PostBackgroundMenuCommand())
		gSchedule.Posted(GetTickCount64(), gCompletionStamp, foregroundProcess == GetCurrentProcessId());
}

// --------------------------------------------------------------------------------------------------------
// Palette heartbeat timer.
//
// Historical 2026 failures motivated menu-command-only execution. The timer
// writes status, counts jobs and schedules the Python menu command. The 2027
// SDK build alone does not verify live execution safety.

static void CALLBACK PumpTimerProc(HWND, UINT, UINT_PTR, DWORD);

void VwxBridge_StartPumpTimer()
{
	if ( gPumpTimer == 0 ) {
		if (!InitializeMenuBroker()) {
			gTriggerState = "menu_broker_initialization_failed";
			gTriggerError = GetLastError();
			++gTriggerFailures;
			WriteSchedulerStatus(VwxPluginDir());
			return;
		}
		gTickPeriod   = kTickIdleMs;      // starts idle, goes hot on first job
		gLastBusyTick = 0;
		gPumpTimer = SetTimer( nullptr, 0, gTickPeriod, PumpTimerProc );
		LogLine( "bridge on (palette open)" );
	}
}

void VwxBridge_StopPumpTimer()
{
	if ( gPumpTimer != 0 ) {
		KillTimer( nullptr, gPumpTimer );
		gPumpTimer = 0;
		LogLine( "bridge off (palette closed)" );
	}
	// Destroying the private target cannot invoke a queued command. Preserve
	// any outstanding completion fence rather than replay it after reopening.
	if (gMenuBrokerWindow != nullptr) {
		const HWND broker = gMenuBrokerWindow;
		gMenuBrokerWindow = nullptr;
		if (DestroyWindow(broker))
			gMenuBroker.TargetDestroyed();
		else
			gMenuBrokerWindow = broker; // Preserve the live target/token on failure.
	}
	gTriggerState = "stopped";
	WriteSchedulerStatus(VwxPluginDir());
	RemoveAlive( VwxPluginDir() );      // external status tooling sees off at once
}

static bool ModalDialogOpen()
{
	// Never dispatch the pump while a dialog-class window is up (message box,
	// modal dialog) — the command couldn't run and might land in the dialog.
	struct Ctx { DWORD pid; bool found; } ctx = { GetCurrentProcessId(), false };
	EnumWindows( [](HWND h, LPARAM lp) -> BOOL {
		Ctx* c = (Ctx*) lp;
		DWORD p = 0;
		GetWindowThreadProcessId( h, &p );
		if ( p == c->pid && IsWindowVisible( h ) ) {
			wchar_t cls[64];
			GetClassNameW( h, cls, 64 );
			if ( wcscmp( cls, L"#32770" ) == 0 ) { c->found = true; return FALSE; }
		}
		return TRUE;
	}, (LPARAM) &ctx );
	return ctx.found;
}

// Timer = heartbeat and posted menu scheduling only. Python executes later
// through the host menu-command runner. Ignore callbacks queued before close.
static void CALLBACK PumpTimerProc(HWND, UINT, UINT_PTR timerId, DWORD)
{
	if ( gPumpTimer == 0 || timerId != gPumpTimer || gTimerCallbackActive || gMenuBroker.active ) return;
	// Nested host loops may run another timer. Do not observe or post from
	// that nested callback.
	struct CallbackGuard {
		CallbackGuard() { gTimerCallbackActive = true; }
		~CallbackGuard() { gTimerCallbackActive = false; }
	} callbackGuard;
	DWORD now = GetTickCount();
	TXString pluginDir = VwxPluginDir();
	gRunnerStamp = ReadRunnerStamp(pluginDir, "pump.stamp");
	gCompletionStamp = ReadRunnerStamp(pluginDir, "pump.complete.stamp");
	const auto beforeTimeouts = gSchedule.timeouts;
	const auto beforeAcknowledged = gSchedule.acknowledged;
	gSchedule.Observe(gCompletionStamp, GetTickCount64());
	if (gSchedule.timeouts != beforeTimeouts)
		LogLine("menu completion not observed; holding outstanding trigger without replay");
	if (gSchedule.acknowledged != beforeAcknowledged)
		gTriggerState = "runner_completion_observed";
	gLastQueue = CountJobs( pluginDir );   // pickup path — must run every tick
	if ( gLastQueue > 0 && !gPaused )
		TriggerPump();
	if ( now - gLastAlive >= kAliveEveryMs ) {
		gLastAlive = now;
		WriteAlive( pluginDir );  // the server tolerates an 8s-old heartbeat,
		                          // so this need not run at tick resolution
	}

	// Adaptive period: hot while there is work or shortly after, idle
	// otherwise. Changing the period of a timer created with a NULL window
	// means killing and recreating it — SetTimer ignores the id for those and
	// hands back a new one.
	if ( gLastQueue > 0 )
		gLastBusyTick = now;
	UINT want = ( now - gLastBusyTick < kCooldownMs ) ? kTickHotMs : kTickIdleMs;
	if ( want != gTickPeriod && gPumpTimer != 0 ) {
		KillTimer( nullptr, gPumpTimer );
		gPumpTimer  = SetTimer( nullptr, 0, want, PumpTimerProc );
		gTickPeriod = want;
	}
}

// --------------------------------------------------------------------------------------------------------
extern const char * DefaultPluginVWRIdentifier();

// NOTE: dispatch-map keys are the bare FUNCTION names — OnFunction receives
// (objName='vwxBridge', functionName='pump'). Registration below uses the
// full dotted name; the map must not.
BEGIN_WebPalette_DISPATCH_MAP(CVwxJSProvider)
ADD_WebPalette_FUNCTION( "pump",   OnPump )
ADD_WebPalette_FUNCTION( "status", OnStatus )
END_WebPalette_DISPATCH_MAP

CVwxJSProvider::CVwxJSProvider( IVWUnknown* parent )
	: VWExtensionPaletteJSProvider( parent )
{
}

CVwxJSProvider::~CVwxJSProvider()
{
}

void CVwxJSProvider::OnInit(IInitContext* context)
{
	fWebFrame = context->GetWebFrame();

	// creates the window.vwxBridge integrator object on the JS side
	context->AddReourceAccessFunction( "vwxBridge", DefaultPluginVWRIdentifier() );

	// Sync callbacks expose status and pause control only; never execute Python.
	context->AddFunctionPromiseSync( "vwxBridge.pump" );
	context->AddFunctionPromiseSync( "vwxBridge.status" );

	// Palette page loaded => palette is visible => bridge on.
	VwxBridge_StartPumpTimer();
}

void CVwxJSProvider::OnPaletteVisibilityChange(bool visible, IWebPaletteFrame* frame)
{
	// Palette open = bridge alive. Palette closed = bridge off. The Pause
	// button in the palette pauses without closing.
	if ( visible )
		VwxBridge_StartPumpTimer();
	else
		VwxBridge_StopPumpTimer();
}

void CVwxJSProvider::OnPump(const TXString& objName, const TXString& functionName, const std::vector<nlohmann::json>& args, VectorWorks::UI::IJSFunctionCallbackContext* context)
{
	// STATUS ONLY — document mutation from the CEF sync callback CRASHES VW
	// (verified live 2026-07-06 with plain vs.Rect; the SDK's own
	// kNotifyGenericWebPalette exists because work must happen "outside the
	// SyncProxy callback"). The drain runs via TriggerPump's deferred paths.
	// pump(true/false) toggles pause without closing the palette.
	if ( !args.empty() && args[0].is_boolean() ) {
		gPaused = args[0].get<bool>();       // pump(true) = pause, pump(false) = resume
		if ( gPumpTimer != 0 ) WriteAlive( VwxPluginDir() );
	}
	nlohmann::json out;
	out["jobs"]     = CountJobs( VwxPluginDir() );
	out["paused"]   = gPaused;
	out["timer"]    = (gPumpTimer != 0);
	out["nativeProbeCount"] = gDispatchCount;
	out["runner"] = "python-menu-command";
	out["scheduler"] = SchedulerStatus();
	context->Resolve( out );
}

void CVwxJSProvider::OnStatus(const TXString& objName, const TXString& functionName, const std::vector<nlohmann::json>& args, VectorWorks::UI::IJSFunctionCallbackContext* context)
{
	nlohmann::json out;
	TXString pluginDir = VwxPluginDir();
	out["pluginDir"] = (const char*) pluginDir;
	out["pluginDirFound"] = !pluginDir.IsEmpty();
	out["jobs"] = CountJobs( pluginDir );
	out["scheduler"] = SchedulerStatus();
	context->Resolve( out );
}

// --------------------------------------------------------------------------------------------------------
CExtVwxBridgePalette::CExtVwxBridgePalette(CallBackPtr)
{
}

CExtVwxBridgePalette::~CExtVwxBridgePalette()
{
}

void CExtVwxBridgePalette::DefineSinks()
{
	this->DefineSink<CVwxJSProvider>( IID_WebJavaScriptProvider );
}

TXString CExtVwxBridgePalette::GetTitle()
{
	return TXResStr("ExtVwxBridgePalette", "paletteName");
}

bool CExtVwxBridgePalette::GetInitialSize(ViewCoord& outCX, ViewCoord& outCY)
{
	outCX = 340;
	outCY = 220;
	return true;
}

bool CExtVwxBridgePalette::GetMinimalSize(ViewCoord& outCX, ViewCoord& outCY)
{
	outCX = 240;
	outCY = 140;
	return true;
}

TXString CExtVwxBridgePalette::GetInitialURL()
{
	const TXString	htmlFolderName	= "html";
	const TXString	htmlFile		= "index.html";
	return VWFC::PluginSupport::GetStandardURL( htmlFolderName, htmlFile );
}

// --------------------------------------------------------------------------------------------------------
// {28AEC847-912F-4C03-9982-F0E7F1AB78F3}
IMPLEMENT_VWPaletteExtension(
	/*Extension class*/	CExtVwxBridgePalette,
	/*Universal name*/	"VwxBridge",
	/*Version*/			1,
	/*UUID*/			0x28aec847, 0x912f, 0x4c03, 0x99, 0x82, 0xf0, 0xe7, 0xf1, 0xab, 0x78, 0xf3 );

// --------------------------------------------------------------------------------------------------------
static SMenuDef		gMenuDef = {
	/*Needs*/				EMenuEnableFlags::None,
	/*NeedsNot*/			EMenuEnableFlags::None,
	/*Title*/				{"ExtMenuShowVwxBridge", "menu_title"},
	/*Category*/			{"ExtMenuShowVwxBridge", "menu_category"},
	/*HelpText*/			{"ExtMenuShowVwxBridge", "menu_helptext"},
	/*VersionCreated*/		30,
	/*VersoinModified*/		0,
	/*VersoinRetired*/		0,
	/*OverrideHelpID*/		" "
};

// --------------------------------------------------------------------------------------------------------
// {6DB485A0-F1BC-4299-A415-7EF65C373C27}
IMPLEMENT_VWMenuExtension(
	/*Extension class*/	CExtMenuShowVwxBridge,
	/*Event sink*/		CExtMenuShowVwxBridge_EventSink,
	/*Universal name*/	"ExtMenuShowVwxBridge",
	/*Version*/			1,
	/*UUID*/			0x6db485a0, 0xf1bc, 0x4299, 0xa4, 0x15, 0x7e, 0xf6, 0x5c, 0x37, 0x3c, 0x27 );

// --------------------------------------------------------------------------------------------------------
CExtMenuShowVwxBridge::CExtMenuShowVwxBridge(CallBackPtr cbp)
	: VWExtensionMenu( cbp, gMenuDef )
{
}

CExtMenuShowVwxBridge::~CExtMenuShowVwxBridge()
{
}

// --------------------------------------------------------------------------------------------------------
CExtMenuShowVwxBridge_EventSink::CExtMenuShowVwxBridge_EventSink(IVWUnknown* parent)
	: VWMenu_EventSink( parent )
{
}

CExtMenuShowVwxBridge_EventSink::~CExtMenuShowVwxBridge_EventSink()
{
}

void CExtMenuShowVwxBridge_EventSink::DoInterface()
{
	gSDK->SetWebPaletteVisibility( CExtVwxBridgePalette::_GetIID(), true );
}

// --------------------------------------------------------------------------------------------------------
// Historical native menu entry retained as a manual status probe.
// It never dispatches Python or consumes queued jobs.
static SMenuDef		gPumpMenuDef = {
	/*Needs*/				EMenuEnableFlags::None,
	/*NeedsNot*/			EMenuEnableFlags::None,
	/*Title*/				{"ExtMenuVwxPump", "menu_title"},
	/*Category*/			{"ExtMenuVwxPump", "menu_category"},
	/*HelpText*/			{"ExtMenuVwxPump", "menu_helptext"},
	/*VersionCreated*/		30,
	/*VersoinModified*/		0,
	/*VersoinRetired*/		0,
	/*OverrideHelpID*/		" "
};

// {234BFD96-FDB4-4C9B-AF64-A5625EACA77B}
IMPLEMENT_VWMenuExtension(
	/*Extension class*/	CExtMenuVwxPump,
	/*Event sink*/		CExtMenuVwxPump_EventSink,
	/*Universal name*/	"ExtMenuVwxPump",
	/*Version*/			1,
	/*UUID*/			0x234bfd96, 0xfdb4, 0x4c9b, 0xaf, 0x64, 0xa5, 0x62, 0x5e, 0xac, 0xa7, 0x7b );

CExtMenuVwxPump::CExtMenuVwxPump(CallBackPtr cbp)
	: VWExtensionMenu( cbp, gPumpMenuDef )
{
}

CExtMenuVwxPump::~CExtMenuVwxPump()
{
}

CExtMenuVwxPump_EventSink::CExtMenuVwxPump_EventSink(IVWUnknown* parent)
	: VWMenu_EventSink( parent )
{
}

CExtMenuVwxPump_EventSink::~CExtMenuVwxPump_EventSink()
{
}

void CExtMenuVwxPump_EventSink::DoInterface()
{
	// DO NOT EXECUTE SCRIPTS HERE. A native menu extension's DoInterface +
	// raw IPythonScriptEngine::ExecuteScript crashed VW on document mutation
	// (verified 2026-07-06, twice: manual click v7 and accelerator v11) —
	// unlike VW's own PYTHON menu-command plugin runner, which wraps script
	// execution in a proper document context. The mutation executor is the
	// "VWX Bridge Start" Python menu command (BridgeStart_MenuCommand.py,
	// menu item); this native command remains only as a status probe.
	gDispatchCount++;
	LogLine( "native DoInterface reached — no-op (mutation executor is the "
	         "'VWX Bridge Start' Python menu command)" );
}
