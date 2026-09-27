//
//	VwxBridgePalette.h — VWX Bridge Native
//
//	The palette reports queue status and schedules the Python menu command.
//	No Python executes from native, web, notification or timer callbacks.
//

#pragma once

namespace VwxBridge
{
	using namespace VectorWorks::Extension;
	using namespace VWFC::PluginSupport;

	// --------------------------------------------------------------------------------------------------------
	class CVwxJSProvider : public VWExtensionPaletteJSProvider
	{
	public:
					CVwxJSProvider(IVWUnknown* parent);
		virtual		~CVwxJSProvider();

		virtual void OnInit(IInitContext* context);
		virtual void OnPaletteVisibilityChange(bool visible, IWebPaletteFrame* frame) override;

		DEFINE_WebPalette_DISPATCH_MAP;

	private:
		void	OnPump  (const TXString& objName, const TXString& functionName, const std::vector<nlohmann::json>& args, VectorWorks::UI::IJSFunctionCallbackContext* context);
		void	OnStatus(const TXString& objName, const TXString& functionName, const std::vector<nlohmann::json>& args, VectorWorks::UI::IJSFunctionCallbackContext* context);
	};

	// --------------------------------------------------------------------------------------------------------
	class CExtVwxBridgePalette : public VWExtensionWebPalette
	{
		DEFINE_VWPaletteExtension;
	public:
					CExtVwxBridgePalette(CallBackPtr);
		virtual		~CExtVwxBridgePalette();

		virtual void		DefineSinks();

		virtual TXString	VCOM_CALLTYPE GetTitle();
		virtual bool		VCOM_CALLTYPE GetInitialSize(ViewCoord& outCX, ViewCoord& outCY);
		virtual bool		VCOM_CALLTYPE GetMinimalSize(ViewCoord& outCX, ViewCoord& outCY);
		virtual TXString	VCOM_CALLTYPE GetInitialURL();
	};

	// --------------------------------------------------------------------------------------------------------
	class CExtMenuShowVwxBridge_EventSink : public VWMenu_EventSink
	{
	public:
					CExtMenuShowVwxBridge_EventSink(IVWUnknown* parent);
		virtual		~CExtMenuShowVwxBridge_EventSink();

		virtual void DoInterface();
	};

	// --------------------------------------------------------------------------------------------------------
	// Historical native menu entry: manual status probe only, never a runner.
	class CExtMenuVwxPump_EventSink : public VWMenu_EventSink
	{
	public:
					CExtMenuVwxPump_EventSink(IVWUnknown* parent);
		virtual		~CExtMenuVwxPump_EventSink();

		virtual void DoInterface();
	};

	class CExtMenuVwxPump : public VWExtensionMenu
	{
		DEFINE_VWMenuExtension;
	public:
					CExtMenuVwxPump(CallBackPtr cbp);
		virtual		~CExtMenuVwxPump();
	};

	// --------------------------------------------------------------------------------------------------------
	class CExtMenuShowVwxBridge : public VWExtensionMenu
	{
		DEFINE_VWMenuExtension;
	public:
					CExtMenuShowVwxBridge(CallBackPtr cbp);
		virtual		~CExtMenuShowVwxBridge();
	};
}
