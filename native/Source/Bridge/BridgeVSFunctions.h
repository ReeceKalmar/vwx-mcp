#pragma once

namespace VwxBridge
{
    using namespace VWFC::PluginSupport;

    class CExtBridgeVSFunctions : public VWExtensionVSFunctions
    {
        DEFINE_VWVSFunctions;
    public:
        explicit CExtBridgeVSFunctions(CallBackPtr cbp);
        virtual ~CExtBridgeVSFunctions();
    };

    class CBridgeVSRoutines : public VWPluginLibraryRoutine
    {
    public:
        CBridgeVSRoutines();
        DEFINE_LIB_DISPATCH_MAP;

    private:
        DWORD fRegistrationThread;
    };
}
