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

        # --- ViewProvider Attachment ---
        if FreeCAD.GuiUp and hasattr(obj, "ViewObject"):
             try:
                 if getattr(obj.ViewObject, "Proxy", None) is None:
                     obj.ViewObject.Proxy = CadQueryFeatureViewProvider(obj.ViewObject)
             except Exception as e:
                 FreeCAD.Console.PrintError(f"Error attaching ViewProvider from __init__: {e}\n")

    def __getstate__(self):
        """Return only serializable data for FreeCAD's PropertyPythonObject."""
        return {'Type': self.Type}

    def __setstate__(self, state):
        """Restore state from serialized data."""
        self.Type = state.get('Type', 'CadQueryFeature')
        self._is_internal_change = False

    def onDocumentRestored(self, obj):
        """Called by FreeCAD after the object is restored from a file."""
        self._is_internal_change = False 

        if FreeCAD.GuiUp and hasattr(obj, "ViewObject"):
            try:
                if getattr(obj.ViewObject, "Proxy", None) is None or not isinstance(obj.ViewObject.Proxy, CadQueryFeatureViewProvider):
                     obj.ViewObject.Proxy = CadQueryFeatureViewProvider(obj.ViewObject)
            except Exception as e:
                FreeCAD.Console.PrintError(f"Error attaching ViewProvider from onDocumentRestored: {e}\n")

        # NB: there is deliberately no rebuild scheduled here. This hook runs
        # BEFORE the restore-time recompute, and FreeCAD purges touched flags
        # once the restore finishes, so touch() and enforceRecompute() are both
        # erased and the object comes back 'Up-to-date'. A document observer is
        # no help either: as of FreeCAD 1.1 no restore-related slot
        # (slotFinishRestoreDocument / slotFinishRestoreObject) is emitted at
        # all during openDocument. So execute() keeps the saved shape and the
        # first explicit recompute picks up code and parameter changes.

    def execute(self, obj):
        """Recomputes the object based on the selected SourceMode and parameters."""
        if cq is None:
            FreeCAD.Console.PrintError(f"Cannot execute '{obj.Label}': CadQuery module is not installed.\n")
            obj.Shape = Part.Shape()
            return

        is_safe = True 
        if cq_utils and hasattr(cq_utils, 'is_safe_to_execute'):
            is_safe = cq_utils.is_safe_to_execute(obj)

        if not is_safe and FreeCAD.GuiUp:
            FreeCAD.Console.PrintWarning(f"Execution of '{obj.Label}' deferred pending document security check.\n")
            if obj.SourceMode != "Frozen":
                 obj.Shape = Part.Shape() 
            return

        # FreeCAD recomputes objects while the document is still being restored.
        # At that point a linked Spreadsheet exists but has NOT yet repopulated
        # its per-cell alias properties, so the parameter loop below finds
        # nothing and the script silently falls back to its own defaults --
        # producing a wrong shape that looks like ParameterSource was ignored.
        # Leave the shape as saved; the first explicit recompute once the
        # document is open rebuilds it with the sheet readable. See the note in
        # onDocumentRestored for why that cannot be scheduled automatically.
        if 'Restore' in obj.State:
            return

        FreeCAD.Console.PrintMessage(f"Executing {obj.Label}...\n")
        source_code = ""

        if obj.SourceMode == "Frozen":
            return

        if obj.SourceMode == "URL":
            if not hasattr(obj, "CodeURL") or not obj.CodeURL:
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
                FreeCAD.Console.PrintError(f"Failed to fetch from URL: {obj.CodeURL}\n")
                obj.Shape = Part.Shape()
                return

        elif obj.SourceMode == "Cache":
            if not obj.CodeCache:
                obj.Shape = Part.Shape()
                return
            source_code = "\n".join(obj.CodeCache)

        if not source_code:
            obj.Shape = Part.Shape()
            return

        collected_shapes = []
        
        def show_shim(cq_object, options=None, name=None):
            collected_shapes.append(cq_object)
        
        def show_object_shim(cq_object, name=None, options=None):
            collected_shapes.append(cq_object)
        
        script_locals = {
            'cq': cq,
            'show': show_shim,
            'show_object': show_object_shim
        }
        
        if hasattr(obj, "ParameterSource") and obj.ParameterSource:
            param_obj = obj.ParameterSource
            try:
                if param_obj.TypeId == 'Spreadsheet::Sheet':
                    for prop_name in param_obj.PropertiesList:
                        if prop_name.startswith('_'): continue
                        try:
                            alias = param_obj.getAlias(prop_name)
                            if alias:
                                value_obj = param_obj.get(prop_name)
                                if value_obj is not None:
                                    # A cell with units comes back as a Quantity;
                                    # a bare number comes back as a plain int,
                                    # float or str with no .Value. Requiring
                                    # .Value silently dropped every unitless
                                    # parameter -- counts, ratios, flags -- and
                                    # the script saw its own default instead.
                                    # Same handling as the VarSet branch below.
                                    value = getattr(value_obj, 'Value', value_obj)
                                    try:
                                        script_locals[alias] = float(value)
                                    except (TypeError, ValueError):
                                        script_locals[alias] = value
                        except Exception: pass

                elif param_obj.TypeId == 'App::VarSet': 
                     for prop_name in param_obj.PropertiesList:
                         if prop_name.startswith('_'): continue
                         prop_obj = param_obj.getPropertyByName(prop_name)
                         value = getattr(prop_obj, 'Value', prop_obj)
                         try:
                             script_locals[prop_name] = float(value)
                         except (TypeError, ValueError):
                             script_locals[prop_name] = value
            except Exception as e:
                 FreeCAD.Console.PrintError(f"Error reading parameters: {e}\n")

        try:
            exec(source_code, script_locals)
            result_obj = None
            
            if collected_shapes:
                if len(collected_shapes) == 1:
                    result_obj = collected_shapes[0]
                else:
                    shapes_to_combine = []
                    for shape in collected_shapes:
                        if isinstance(shape, cq.Workplane):
                            shapes_to_combine.append(shape.val())
                        elif isinstance(shape, cq.Shape):
                            shapes_to_combine.append(shape)
                    if shapes_to_combine:
                        result_obj = cq.Compound.makeCompound(shapes_to_combine)
            
            if result_obj is None:
                result_obj = script_locals.get('result')

            if not result_obj:
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
                    raise TypeError("Result extraction failed.")

                actual_shape.exportBrep(brep_stream)
                part_shape = Part.Shape()
                brep_string = brep_stream.getvalue().decode('utf-8')
                part_shape.importBrepFromString(brep_string)
                obj.Shape = part_shape

        except Exception:
            FreeCAD.Console.PrintError(f"Error executing script:\n{traceback.format_exc()}\n")
            obj.Shape = Part.Shape()


    def onChanged(self, obj, prop):
        """Handles property changes."""
        if getattr(self, '_is_internal_change', False):
            return

        if not hasattr(obj, "Document") or not obj.Document:
             return

        if prop == "CodeCache":
            if obj.SourceMode != "Cache":
                obj.SourceMode = "Cache"
            else:
                self.execute(obj)
            return

        if prop == "SourceMode" or prop == "ParameterSource":
            if not (prop == "SourceMode" and obj.SourceMode == "Frozen"):
                self.execute(obj)
            return

# --- View Provider Class ---
class CadQueryFeatureViewProvider:
    """Controls how the CadQueryFeature object appears in the GUI."""

    def __init__(self, vobj):
        """Called when the ViewObject is created or restored."""
        vobj.Proxy = self
        # REMOVED: self.ViewObject = vobj 
        # Storing the C++ ViewObject in the Python Proxy causes JSON serialization failure.

    def __getstate__(self):
        """Return empty dict; no serializable state needed for this ViewProvider."""
        return {}

    def __setstate__(self, state):
        pass

    def getIcon(self):
        """Returns the absolute path to the icon."""
        return os.path.join(ICON_PATH, "CQ_Logo.svg")

    def _triggerEditCode(self, viewObject):
        """Action for the 'Edit Code' context menu item."""
        dataObject = viewObject.Object
        if dataObject and cq_editor_tools:
             cq_editor_tools.launch_editor_for_feature(dataObject)

    def setupContextMenu(self, viewObject, menu):
        """Adds items to the context menu."""
        if not QtGui: return 

        edit_icon_path = os.path.join(ICON_PATH, "CQ_Edit.svg")
        if os.path.exists(edit_icon_path):
            action = menu.addAction(QtGui.QIcon(edit_icon_path), "Edit CadQuery Code")
        else:
            action = menu.addAction("Edit CadQuery Code")

        action.triggered.connect(lambda: self._triggerEditCode(viewObject))
