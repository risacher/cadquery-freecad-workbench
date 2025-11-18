# In cq_feature.py

import FreeCAD
import urllib.request
import os
import traceback
from io import BytesIO
from urllib.parse import urlparse
import Part # Import Part module

# --- Defer cadquery import until needed ---
cq = None
try:
    import cadquery as cq
    FreeCAD.Console.PrintMessage("CadQuery module loaded successfully.\n")
except ImportError:
    FreeCAD.Console.PrintWarning("CadQuery module not found. CadQuery features will not execute until CadQuery is installed.\n")

# --- Define paths relative to this file ---
WB_ROOT = os.path.dirname(__file__)
ICON_PATH = os.path.join(WB_ROOT, "CQGui", "icons")

# --- Import PySide/Qt ---
try:
    from PySide6 import QtGui, QtCore, QtWidgets
except ImportError:
    try:
        from PySide2 import QtGui, QtCore, QtWidgets
    except ImportError:
        try:
            # Fallback for very old FreeCAD versions
            from PySide import QtGui, QtCore
            # PySide (Qt4) puts QPlainTextEdit in QtGui
            QtWidgets = QtGui
        except ImportError:
            QtGui = None
            QtCore = None
            QtWidgets = None
            FreeCAD.Console.PrintError("Could not import PySide/Qt modules. GUI features may fail.\n")


# --- Import editor tools for context menu ---
try:
    # Try relative import first (standard within a package)
    from . import cq_editor_tools
except ImportError:
    # Fallback if run directly or module structure changes
    try:
        import cq_editor_tools
    except ImportError:
        cq_editor_tools = None
        FreeCAD.Console.PrintWarning("Could not import cq_editor_tools. 'Edit Code' context menu may fail.\n")

# --- MODIFIED: Import the safety check function from cq_utils ---
try:
    # Assuming cq_utils.py is in the same directory or Python path
    import cq_utils
    FreeCAD.Console.PrintMessage("Successfully imported cq_utils for security checks.\n")
except ImportError:
    cq_utils = None
    FreeCAD.Console.PrintWarning("Could not import cq_utils. Security check on load will be bypassed.\n")
    # Define a dummy function if import fails to prevent NameError later
    def is_safe_to_execute(obj): return True


# --- Data Proxy Class ---
class CadQueryFeature:
    """The Python Proxy class that gives our object its data intelligence."""

    def __init__(self, obj):
        """Called when the object is *first* created in the GUI."""
        FreeCAD.Console.PrintMessage(f"CadQueryFeature __init__ called for {obj.Label}\n")
        obj.Proxy = self
        self.Type = 'CadQueryFeature'
        self._is_internal_change = False # Flag for onChanged re-entrancy

        # --- Define Properties ---
        if not hasattr(obj, "SourceMode"):
            obj.addProperty("App::PropertyEnumeration", "SourceMode", "CadQuery", "The source of the script to execute").SourceMode = ["URL", "Cache", "Frozen"]
            obj.SourceMode = "Frozen" # Default to Frozen
        if not hasattr(obj, "CodeURL"):
            obj.addProperty("App::PropertyString", "CodeURL", "CadQuery", "URL to the source .py file").CodeURL = ""
        if not hasattr(obj, "CacheEnabled"):
            obj.addProperty("App::PropertyBool", "CacheEnabled", "CadQuery", "Update the cache when computing from URL").CacheEnabled = True
        if not hasattr(obj, "CodeCache"):
            obj.addProperty("App::PropertyStringList", "CodeCache", "CadQuery", "A local cache of the source code")
        if not hasattr(obj, "ParameterSource"):
            obj.addProperty("App::PropertyLink", "ParameterSource", "CadQuery", "Optional Spreadsheet or VarSet for parameters")

        # --- ViewProvider Attachment (Attempt in __init__ for robustness) ---
        if FreeCAD.GuiUp and hasattr(obj, "ViewObject"):
             try:
                 if getattr(obj.ViewObject, "Proxy", None) is None:
                     obj.ViewObject.Proxy = CadQueryFeatureViewProvider(obj.ViewObject)
                     FreeCAD.Console.PrintMessage("ViewProvider attached from __init__.\n")
             except Exception as e:
                 FreeCAD.Console.PrintError(f"Error attaching ViewProvider from __init__: {e}\n{traceback.format_exc()}\n")


    def onDocumentRestored(self, obj):
        """Called by FreeCAD after the object is restored from a file."""
        FreeCAD.Console.PrintMessage(f"CadQueryFeature onDocumentRestored called for {obj.Label}\n")
        self._is_internal_change = False # Reset flag on load

        # Attach the ViewProvider proxy if in GUI mode
        if FreeCAD.GuiUp and hasattr(obj, "ViewObject"):
            FreeCAD.Console.PrintMessage("Attempting to attach ViewProvider from onDocumentRestored...\n")
            try:
                if getattr(obj.ViewObject, "Proxy", None) is None or not isinstance(obj.ViewObject.Proxy, CadQueryFeatureViewProvider):
                     obj.ViewObject.Proxy = CadQueryFeatureViewProvider(obj.ViewObject)
                     FreeCAD.Console.PrintMessage("ViewProvider attached successfully from onDocumentRestored.\n")
                else:
                    FreeCAD.Console.PrintMessage("ViewProvider already attached during onDocumentRestored.\n")

            except Exception as e:
                FreeCAD.Console.PrintError(f"Error attaching ViewProvider from onDocumentRestored: {e}\n{traceback.format_exc()}\n")
        else:
             FreeCAD.Console.PrintWarning(f"Object {obj.Label} restored without ViewObject (possibly console mode).\n")

    def execute(self, obj):
        """Recomputes the object based on the selected SourceMode and parameters."""
        # --- Check if cadquery is available ---
        if cq is None:
            FreeCAD.Console.PrintError(f"Cannot execute '{obj.Label}': CadQuery module is not installed.\n")
            FreeCAD.Console.PrintError("Please install CadQuery using the workbench menu: CadQuery -> Install -> Install CadQuery (Stable)\n")
            obj.Shape = Part.Shape()
            return

        # --- MODIFIED Safety Check ---
        # Use the imported function from cq_utils
        is_safe = True # Default to safe if cq_utils failed to import
        if cq_utils and hasattr(cq_utils, 'is_safe_to_execute'):
            is_safe = cq_utils.is_safe_to_execute(obj)

        # Only block execution if we're in GUI mode AND the check hasn't passed
        if not is_safe and FreeCAD.GuiUp:
            FreeCAD.Console.PrintWarning(f"Execution of '{obj.Label}' deferred pending document security check.\n")
            if obj.SourceMode != "Frozen":
                 obj.Shape = Part.Shape() # Clear shape if deferred
            return
        # --- End Safety Check ---

        FreeCAD.Console.PrintMessage(f"Executing {obj.Label}...\n")
        source_code = ""

        # --- Handle Frozen State ---
        if obj.SourceMode == "Frozen":
            FreeCAD.Console.PrintMessage(f"'{obj.Label}' is Frozen, skipping execution.\n")
            return

        # --- Get Source Code ---
        if obj.SourceMode == "URL":
            if not hasattr(obj, "CodeURL") or not obj.CodeURL:
                FreeCAD.Console.PrintWarning("SourceMode is URL, but CodeURL is empty or missing.\n")
                obj.Shape = Part.Shape()
                return
            try:
                hdr = {'User-Agent': 'FreeCAD-CadQuery-Workbench'}
                req = urllib.request.Request(obj.CodeURL, headers=hdr)
                with urllib.request.urlopen(req) as response:
                    source_code = response.read().decode('utf-8')
                if obj.CacheEnabled:
                    self._is_internal_change = True
                    try:
                        obj.CodeCache = source_code.splitlines()
                    finally:
                        self._is_internal_change = False
            except Exception:
                FreeCAD.Console.PrintError(f"Failed to fetch from URL: {obj.CodeURL}\n{traceback.format_exc()}\n")
                obj.Shape = Part.Shape()
                return

        elif obj.SourceMode == "Cache":
            if not obj.CodeCache:
                FreeCAD.Console.PrintWarning("SourceMode is Cache, but CodeCache is empty.\n")
                obj.Shape = Part.Shape()
                return
            source_code = "\n".join(obj.CodeCache)

        if not source_code:
            FreeCAD.Console.PrintError("No source code available to execute.\n")
            obj.Shape = Part.Shape()
            return

        # --- Extract Parameters ---
        script_locals = {'cq': cq}
        if hasattr(obj, "ParameterSource") and obj.ParameterSource:
            param_obj = obj.ParameterSource
            FreeCAD.Console.PrintMessage(f"Loading parameters from: {param_obj.Label} ({param_obj.TypeId})\n")
            try:
                if param_obj.TypeId == 'Spreadsheet::Sheet':
                    for prop_name in param_obj.PropertiesList:
                        if prop_name.startswith('_'): continue
                        try:
                            alias = param_obj.getAlias(prop_name)
                            if alias:
                                value_obj = param_obj.get(prop_name)
                                if value_obj is not None and hasattr(value_obj, 'Value'):
                                    script_locals[alias] = float(value_obj.Value)
                                    FreeCAD.Console.PrintMessage(f"  Loaded Spreadsheet param: {alias} (from cell {prop_name}) = {script_locals[alias]}\n")
                                else:
                                    FreeCAD.Console.PrintWarning(f"  Spreadsheet alias '{alias}' (cell {prop_name}) has no value or is not a Quantity.\n")
                        except Exception:
                             pass

                elif param_obj.TypeId == 'App::VarSet': # VarSet
                     FreeCAD.Console.PrintMessage("Processing VarSet...\n")
                     for prop_name in param_obj.PropertiesList:
                         if prop_name.startswith('_'): continue
                         prop_obj = param_obj.getPropertyByName(prop_name)
                         value = getattr(prop_obj, 'Value', prop_obj)
                         final_value = None
                         try:
                             final_value = float(value)
                         except (TypeError, ValueError):
                             final_value = value

                         script_locals[prop_name] = final_value
                         FreeCAD.Console.PrintMessage(f"  Loaded VarSet param: {prop_name} = {script_locals[prop_name]} (type: {type(script_locals[prop_name])})\n")
                else:
                    FreeCAD.Console.PrintWarning(f"Linked ParameterSource object '{param_obj.Label}' is not a Spreadsheet or VarSet ({param_obj.TypeId}).\n")

            except Exception as e:
                 FreeCAD.Console.PrintError(f"Error reading parameters from '{param_obj.Label}': {e}\n{traceback.format_exc()}\n")


        # --- Execute Script ---
        try:
            exec(source_code, script_locals)
            result_obj = script_locals.get('result') or script_locals.get('show_object')

            if not result_obj:
                FreeCAD.Console.PrintWarning("Script executed but did not produce a 'result' or 'show_object'.\n")
                obj.Shape = Part.Shape()
                return

            brep_stream = BytesIO()
            if isinstance(result_obj, (cq.Workplane, cq.Shape)):
                shape_to_export = result_obj.val() if isinstance(result_obj, cq.Workplane) else result_obj
                actual_shape = None
                if isinstance(shape_to_export, cq.Shape):
                    actual_shape = shape_to_export
                elif hasattr(shape_to_export, "val") and callable(shape_to_export.val):
                   val_result = shape_to_export.val()
                   if isinstance(val_result, cq.Shape):
                       actual_shape = val_result

                if actual_shape is None:
                    raise TypeError("Result is not a valid CadQuery Shape or could not be extracted from Workplane.")

                actual_shape.exportBrep(brep_stream)
                part_shape = Part.Shape()
                brep_string = brep_stream.getvalue().decode('utf-8')
                part_shape.importBrepFromString(brep_string)
                if part_shape.isNull():
                     raise ValueError("Failed to import BRep string into Part.Shape. BRep might be invalid.")
                obj.Shape = part_shape
                FreeCAD.Console.PrintMessage(f"Successfully updated shape for {obj.Label}.\n")

            else:
                FreeCAD.Console.PrintError(f"Result object type ({type(result_obj).__name__}) not supported. Expected CadQuery Workplane or Shape.\n")
                obj.Shape = Part.Shape()
                return

        except Exception:
            FreeCAD.Console.PrintError(f"Error executing script for {obj.Label}:\n{traceback.format_exc()}\n")
            obj.Shape = Part.Shape()


    def onChanged(self, obj, prop):
        """Handles property changes."""
        if getattr(self, '_is_internal_change', False):
            return

        FreeCAD.Console.PrintMessage(f"onChanged called for {obj.Label}, property: {prop}\n")

        if not hasattr(obj, "Document") or not obj.Document:
             return

        if prop == "CodeCache":
            if obj.SourceMode != "Cache":
                FreeCAD.Console.PrintMessage("CodeCache edited, automatically switching SourceMode to 'Cache'.\n")
                obj.SourceMode = "Cache"
            else:
                self.execute(obj)
            return

        if prop == "SourceMode" or prop == "ParameterSource":
            if not (prop == "SourceMode" and obj.SourceMode == "Frozen"):
                self.execute(obj)
            return

        if prop == "CodeURL" and obj.SourceMode == "URL":
            if not obj.CacheEnabled:
                 self.execute(obj)
            else:
                 pass

# --- View Provider Class ---
class CadQueryFeatureViewProvider:
    """Controls how the CadQueryFeature object appears in the GUI."""

    def __init__(self, vobj):
        """Called when the ViewObject is created or restored."""
        obj_label = getattr(vobj.Object, "Label", "<Unknown>")
        FreeCAD.Console.PrintMessage(f"ViewProvider __init__ called for object: {obj_label}\n")
        vobj.Proxy = self
        self.ViewObject = vobj # Store for potential future use

    def getIcon(self):
        """Returns the absolute path to the icon for the Tree View."""
        icon_path = os.path.join(ICON_PATH, "CQ_Logo.svg")
        if not os.path.exists(icon_path):
             FreeCAD.Console.PrintWarning(f"getIcon: Icon file not found at path: {icon_path}\n")
        return icon_path

    def _triggerEditCode(self, viewObject):
        """Action for the 'Edit Code' context menu item."""
        FreeCAD.Console.PrintMessage("_triggerEditCode called!\n")
        dataObject = viewObject.Object
        if dataObject and cq_editor_tools:
             cq_editor_tools.launch_editor_for_feature(dataObject)
        elif not cq_editor_tools:
            FreeCAD.Console.PrintError("cq_editor_tools module not loaded, cannot launch editor.\n")
        else:
             FreeCAD.Console.PrintError("Could not get data object from view object in context menu action.\n")

    def setupContextMenu(self, viewObject, menu):
        """Adds items to the context menu."""
        if not QtGui: return # Safety check if Qt import failed

        obj_label = getattr(viewObject.Object, "Label", "<Unknown>")
        FreeCAD.Console.PrintMessage(f"setupContextMenu called for: {obj_label}\n")

        edit_icon_path = os.path.join(ICON_PATH, "CQ_Edit.svg")

        if os.path.exists(edit_icon_path):
            edit_icon = QtGui.QIcon(edit_icon_path)
            action = menu.addAction(edit_icon, "Edit CadQuery Code")
        else:
            FreeCAD.Console.PrintWarning(f"setupContextMenu: Edit icon not found at {edit_icon_path}\n")
            action = menu.addAction("Edit CadQuery Code") # Add without icon

        action.triggered.connect(lambda: self._triggerEditCode(viewObject))
