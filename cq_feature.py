# In cq_feature.py

import FreeCAD
import urllib.request
import os
import sys
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


def local_script_path(obj):
    """Filesystem path of the script, when CodeURL is a file:// URL, else None."""
    url = getattr(obj, "CodeURL", "") or ""
    if getattr(obj, "SourceMode", None) != "URL" or not url:
        return None
    parts = urlparse(url)
    if parts.scheme != "file":
        return None
    return urllib.request.url2pathname(parts.path)


def to_cq_shape(result_obj):
    """Coerce whatever the script produced into a single cadquery Shape.

    This used to be an `isinstance(result_obj, (cq.Workplane, cq.Shape))` test
    with no else branch, so anything else -- a cq.Assembly, a cq.Sketch, a
    build123d object -- left obj.Shape untouched and reported nothing at all.
    The script appeared to run and simply had no effect, which is the hardest
    kind of failure to chase. Unsupported types now raise.
    """
    if isinstance(result_obj, cq.Workplane):
        result_obj = result_obj.val()

    if isinstance(result_obj, cq.Shape):
        return result_obj

    # cq.Assembly
    to_compound = getattr(result_obj, "toCompound", None)
    if callable(to_compound):
        shape = to_compound()
        if isinstance(shape, cq.Shape):
            return shape

    # build123d, and anything else holding a raw OCCT TopoDS_Shape
    wrapped = getattr(result_obj, "wrapped", None)
    if wrapped is not None:
        try:
            return cq.Shape.cast(wrapped)
        except Exception:
            pass

    raise TypeError(
        f"cannot turn a {type(result_obj).__name__} into a shape; return a "
        f"cadquery Workplane, Shape or Assembly, or a build123d object")


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

    @staticmethod
    def _fail(obj, message, level="error"):
        """Report a failure WITHOUT discarding the last good shape.

        Every error path used to assign Part.Shape(), so a transient problem --
        being offline with SourceMode=URL, a syntax error mid-edit -- silently
        deleted the geometry and you had to rebuild to get it back. The shape is
        now only ever replaced by a successful build.
        """
        text = f"{obj.Label}: {message} (keeping the last built shape)\n"
        if level == "warning":
            FreeCAD.Console.PrintWarning(text)
        else:
            FreeCAD.Console.PrintError(text)

    def execute(self, obj):
        """Recomputes the object based on the selected SourceMode and parameters."""
        if cq is None:
            self._fail(obj, "CadQuery module is not installed")
            return

        is_safe = True
        if cq_utils and hasattr(cq_utils, 'is_safe_to_execute'):
            is_safe = cq_utils.is_safe_to_execute(obj)

        if not is_safe and FreeCAD.GuiUp:
            self._fail(obj, "execution deferred pending document security check",
                       level="warning")
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

        # Frozen means "do not run"; say nothing rather than logging a build
        # that is not about to happen.
        if obj.SourceMode == "Frozen":
            return

        FreeCAD.Console.PrintMessage(f"Executing {obj.Label}...\n")
        source_code = ""

        if obj.SourceMode == "URL":
            if not hasattr(obj, "CodeURL") or not obj.CodeURL:
                self._fail(obj, "SourceMode is URL but CodeURL is empty")
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
            except Exception as e:
                self._fail(obj, f"failed to fetch {obj.CodeURL}: {e}")
                return

        elif obj.SourceMode == "Cache":
            if not obj.CodeCache:
                self._fail(obj, "SourceMode is Cache but CodeCache is empty")
                return
            source_code = "\n".join(obj.CodeCache)

        if not source_code:
            self._fail(obj, "no source code to execute")
            return

        collected_shapes = []
        
        def show_shim(cq_object, options=None, name=None):
            collected_shapes.append(cq_object)
        
        def show_object_shim(cq_object, name=None, options=None):
            collected_shapes.append(cq_object)
        
        script_locals = {
            'cq': cq,
            'show': show_shim,
            'show_object': show_object_shim,
            # exec() does not define __name__, so it resolves through
            # __builtins__ to 'builtins' and a script's
            # `if __name__ == "__main__":` block silently never runs -- the
            # script loads and appears to do nothing. Most CadQuery scripts are
            # written to also be runnable on their own, so this matters.
            '__name__': '__main__',
        }

        # Give a file:// script the same footing it would have if run directly:
        # it can find its own assets and import modules sitting next to it.
        script_path = local_script_path(obj)
        if script_path:
            script_locals['__file__'] = script_path
            script_dir = os.path.dirname(script_path)
            if script_dir and script_dir not in sys.path:
                sys.path.insert(0, script_dir)


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

            if result_obj is None:
                self._fail(obj, "the script produced no result: call show_object(), "
                                "or leave the shape in a variable named 'result'")
                return

            # Raises TypeError on anything it cannot handle, rather than
            # silently leaving the shape untouched.
            actual_shape = to_cq_shape(result_obj)

            brep_stream = BytesIO()
            actual_shape.exportBrep(brep_stream)
            part_shape = Part.Shape()
            part_shape.importBrepFromString(brep_stream.getvalue().decode('utf-8'))
            obj.Shape = part_shape

        except Exception:
            FreeCAD.Console.PrintError(
                f"Error executing script for {obj.Label}:\n{traceback.format_exc()}")
            self._fail(obj, "script raised; shape not updated")


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
