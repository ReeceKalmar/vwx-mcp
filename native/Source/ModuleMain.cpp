//
//	ModuleMain.cpp — VWX Bridge Native (menu scheduler and status palette)
//
//	Registers:
//	  - CExtVwxBridgePalette  : modeless web palette displaying bridge status
//	  - CExtMenuShowVwxBridge : menu command that shows the palette
//	  - CExtMenuVwxPump       : manual status probe; Python uses VWX Bridge Start
//	  - CExtBridgeVSFunctions : guarded native helpers exposed to the Python menu runner
//

#include "StdAfx.h"

#ifdef VWX_EXPECTED_SDK_VERSION
static_assert(SDK_VERSION == VWX_EXPECTED_SDK_VERSION, "Wrong Vectorworks SDK for this build");
#endif

#include "Bridge/VwxBridgePalette.h"
#include "Bridge/BridgeVSFunctions.h"

const char * DefaultPluginVWRIdentifier() { return "VwxBridge"; }

//------------------------------------------------------------------
// provide SDK version for which this plugin was compiled
extern "C" Sint32 GS_EXTERNAL_ENTRY plugin_module_ver() { return SDK_VERSION; }

//------------------------------------------------------------------
extern "C" Sint32 GS_EXTERNAL_ENTRY plugin_module_main(Sint32 action, void* moduleInfo, const VWIID& iid, IVWUnknown*& inOutInterface, CallBackPtr cbp)
{
	::GS_InitializeVCOM( cbp );

	Sint32	reply	= 0L;

	using namespace VWFC::PluginSupport;

	// NOTE: no side effects here — arming anything from module registration
	// crashes VW during boot (verified live, twice). The pump timer starts
	// and stops with the palette's visibility (Bridge/VwxBridgePalette.cpp).
	REGISTER_Extension<VwxBridge::CExtVwxBridgePalette>( GROUPID_ExtensionWebPalettes, action, moduleInfo, iid, inOutInterface, cbp, reply );
	REGISTER_Extension<VwxBridge::CExtMenuShowVwxBridge>( GROUPID_ExtensionMenu, action, moduleInfo, iid, inOutInterface, cbp, reply );
	REGISTER_Extension<VwxBridge::CExtMenuVwxPump>( GROUPID_ExtensionMenu, action, moduleInfo, iid, inOutInterface, cbp, reply );
	REGISTER_Extension<VwxBridge::CExtBridgeVSFunctions>( GROUPID_ExtensionVSFunctions, action, moduleInfo, iid, inOutInterface, cbp, reply );

	return reply;
}
