"""Prevent known interactive operations in unattended MCP sessions.

This is an execution preference, not a Python security sandbox. Native plug-ins
can still display error dialogs. Arbitrary scripts/menu commands are excluded
because their interaction requirements cannot be inferred from a tool name.
"""
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_COMMANDS = frozenset({
    'execute_script', 'run_menu_command', 'marionette_recalc',
    'save_document', 'create_space', 'create_pio', 'switch_document',
    'export_pdf', 'export_dxf', 'export_image', 'export_shp', 'export_ifc',
    'import_image', 'import_dwg',
})
# Supplement SDK category metadata with documented file pickers, editors and
# indirect script/menu/tool invocation. SaveActiveDocument is explicitly quiet.
INTERACTIVE_SDK = frozenset({
    'AcquireExportPDFSettingsAndLocation', 'DoMenuTextByName', 'CallTool',
    'CallToolByName', 'Run', 'RunScript', 'PythonExecute', 'PythonExecuteFile',
    'RunTempTool', 'SetTool', 'SetToolByName', 'SetToolByIndex', 'SetToolWithMode',
    'GetFile', 'GetFileN', 'GetFolder', 'PutFile', 'GetFileFromFolder',
    'RunLayoutDialog', 'RunLayoutDialogN', 'RunNamedDialog', 'RunNamedDialogN',
    'DisplayLayerScaleDialog', 'DisplayOrganizationDialog', 'GS_EdSh_RunDialog',
    'ShowCreateImageDialog', 'ShowEditTileDialog', 'ShowEditTileSettingsDialog',
    'ShowGradientEditorDialog', 'ShowNewTileDialog', 'ShowWSDialog',
    'PrintUsingPrintDialog', 'PrintWithoutUsingPrintDialog', 'EditObject',
    'EditProperties', 'EditSymbol', 'EditTexture', 'ShowHelp', 'OpenURL',
    'AlertCritical', 'AlertInform', 'AlertInformDontShowAgain', 'SysBeep',
    # SDK descriptions explicitly open editors, pickers or preference dialogs.
    'AdditionalDefRecords', 'CallToolWithMode', 'CreateTextureBitmapN',
    'DBShowDBTableDlg', 'DBShowManageDBsDlg', 'DBShowObjConnDlg',
    'DTM6_ShowSendEdgeDlg', 'EA_DataAccAdvDlg', 'EA_DataAccMtrlDlg',
    'EditGeorefWithUI', 'EditObjectSpecial', 'EditOpenGLPrefs',
    'EditRenderWorksPrefs', 'EditShaderRecord', 'EditTextureBitmap',
    'EditTextureSpace', 'GetCatalogItem', 'OLDHoistSectionDlg',
    'OLDTrussSectionDlg', 'ObjPropsEditDlg', 'RunGridSettingsDlg',
    'RunNewColorPalette', 'SM_Preferences', 'SelectPluginCatalog',
    'ShowPlanShadowsTab', 'ShowWebDlg', 'TBB_OpenTBBSelDlg',
    'DisplayContextHelpOfCurrentPlugin',
    # These entry points can prompt, even when a path or prior options exist.
    'ExportDXFDWG', 'ImportDXFDWG', 'ImportDXFDWGFile', 'ImportSingleDXFDWG',
    'IFC_ExportWithUI', 'IFC_ImportWithUI', 'LegacyShapefileExp',
    'LegacyShapefileImp', 'ImportImageFile', 'ImportImageFileN', 'ImportResourceToCurrentFile',
    'CreateCustomObjectN', 'ResList_ImportItemN', 'QTSetMovieOptions', 'QTSetMovieOptionsN',
})


@lru_cache(maxsize=1)
def catalog():
    return json.loads((ROOT / 'vwx-plugin/sdk_catalog.json').read_text(encoding='utf-8'))['functions']


def _error(command, reason):
    return {'error': reason, 'code': 'VWX_BACKGROUND_INTERACTION_REQUIRED',
            'command': command, 'dispatched': False, 'background_mode': True,
            'alternative': 'Use sdk_call/sdk_sequence or a non-interactive workflow. '
                           'For attended operations, restart the MCP server with VWX_BACKGROUND_MODE=0.'}


def check(command, params=None, *, sdk_catalog=None, depth=0):
    """Preflight the whole batch/sequence before any native mutation is queued."""
    params = {} if params is None else params
    if not isinstance(command, str) or not isinstance(params, dict) or depth > 20:
        return _error(str(command), 'Cannot validate this command envelope for background execution.')
    if command == 'bridge_maintenance' and depth:
        return {'error': 'Maintenance actions must be separate top-level typed requests',
                'code': 'VWX_MAINTENANCE_CONTEXT', 'command': command, 'dispatched': False}
    if command == 'create_pio' and params.get('show_pref', False) is False:
        # The documented flag suppresses the preferences dialog. Errors inside
        # a third-party object can still surface; this is not a sandbox.
        return None
    if command in BLOCKED_COMMANDS:
        if command == 'switch_document':
            # The legacy non-MDI fallback restores/foregrounds a window. Even
            # its posted MDI path changes the process-wide active document;
            # it does not provide an isolated document for each MCP session.
            result = _error(command, 'Document switching can restore or foreground Vectorworks '
                            'and changes its shared active document.')
            result['alternative'] = ('Keep the intended document active for background work. '
                                     'Use an attended session for document switching; '
                                     'MCP sessions do not isolate Vectorworks documents.')
            return result
        return _error(command, 'This operation can require desktop interaction or execute unchecked code.')
    if command == '_batch':
        calls = params.get('calls', [])
        if not isinstance(calls, list):
            return _error(command, 'Batch calls must be an array.')
        for index, call in enumerate(calls):
            if not isinstance(call, dict):
                return _error(command, 'Invalid batch call.')
            denied = check(call.get('command'), call.get('params', {}),
                           sdk_catalog=sdk_catalog, depth=depth + 1)
            if denied:
                return dict(denied, blocked_step=index)
        return None
    if command == 'sdk_sequence':
        calls = params.get('calls', [])
        if not isinstance(calls, list):
            return _error(command, 'Sequence calls must be an array.')
        for index, call in enumerate(calls):
            if not isinstance(call, dict):
                return _error(command, 'Invalid SDK sequence call.')
            denied = check('sdk_call', call, sdk_catalog=sdk_catalog, depth=depth + 1)
            if denied:
                return dict(denied, blocked_step=index)
        return None
    if command in {'sdk_list', 'sdk_test_status'}:
        return None
    if command == 'sdk_call' or command.startswith('sdk_'):
        name = params.get('name') if command == 'sdk_call' else command[4:]
        entries = catalog() if sdk_catalog is None else sdk_catalog
        if not isinstance(name, str) or name not in entries:
            return _error(command, 'Unknown SDK contract; background requirements cannot be checked.')
        entry = entries[name]
        if name == 'DTM6_GetDTMObject':
            arguments = params.get('arguments')
            if not isinstance(arguments, dict) or arguments.get('bPickUpModel') is not False:
                result = _error(command, 'DTM6_GetDTMObject may open the site-model picker; '
                                'bPickUpModel must be explicitly false for background execution.')
                result['alternative'] = ('Use site_model_on_layer for unambiguous layer-local discovery, '
                                         'or query a previously verified site_model_id. '
                                         'The SDK call requires arguments.bPickUpModel=false.')
                return result
        if (name == 'CreateCustomObjectN' and isinstance(params.get('arguments'), dict)
                and params['arguments'].get('showPref') is False):
            return None
        if (name in INTERACTIVE_SDK or entry.get('context', {}).get('interactive')
                or entry.get('category') in {'User Interactive', 'Dialogs - Predefined'}):
            return _error(command, name + ' requires or can initiate interactive Vectorworks UI.')
    return None
