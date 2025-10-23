# In a new file, for example, cq_feature.py

import FreeCAD
import cadquery as cq
import urllib.request

import os  
WB_ROOT = os.path.dirname(__file__)
ICON_PATH = os.path.join(WB_ROOT, "CQGui", "icons")


class CadQueryFeature:
    """The Python Proxy class that gives our object its intelligence."""

    def __init__(self, obj):
        """This is called only when the object is *first* created."""
        FreeCAD.Console.PrintMessage(f"CadQueryFeature __init__ called for {obj.Label}\n") 
        obj.Proxy = self
        self.Type = 'CadQueryFeature'
        self._is_internal_change = False
        
        # Add properties ONLY if they don't already exist (important for file load)
        if not hasattr(obj, "SourceMode"):
            obj.addProperty("App::PropertyEnumeration", "SourceMode", "CadQuery", "The source of the script to execute").SourceMode = ["URL", "Cache", "Frozen"]
        if not hasattr(obj, "CodeURL"):
            obj.addProperty("App::PropertyString", "CodeURL", "CadQuery", "URL to the source .py file").CodeURL = ""
        if not hasattr(obj, "CacheEnabled"):
            obj.addProperty("App::PropertyBool", "CacheEnabled", "CadQuery", "Update the cache when computing from URL").CacheEnabled = True
        if not hasattr(obj, "CodeCache"):
            obj.addProperty("App::PropertyStringList", "CodeCache", "CadQuery", "A local cache of the source code")
        
        # --- REMOVED: ViewProvider attachment logic is no longer done here ---

    def onDocumentRestored(self, obj):
        """Called when the object is restored from a file."""
        FreeCAD.Console.PrintMessage(f"CadQueryFeature onDocumentRestored called for {obj.Label}\n")
        self._is_internal_change = False # Ensure flag is reset on load
        
        # Attach the ViewProvider here, ensuring ViewObject exists.
        if hasattr(obj, "ViewObject"):
            FreeCAD.Console.PrintMessage("Attempting to attach ViewProvider from onDocumentRestored...\n") 
            try:
                # Explicitly create and assign the instance, like the forum example
                obj.ViewObject.Proxy = CadQueryFeatureViewProvider(obj.ViewObject)
                FreeCAD.Console.PrintMessage("ViewProvider attached successfully from onDocumentRestored.\n") 
            except Exception as e:
                FreeCAD.Console.PrintError(f"Error attaching ViewProvider from onDocumentRestored: {e}\n")
        else:
             FreeCAD.Console.PrintWarning(f"Object {obj.Label} restored without ViewObject, cannot attach ViewProvider.\n")
        
    def execute(self, obj):
        """
        Recomputes the object based on the selected SourceMode.
        """
        import FreeCAD, Part, cadquery as cq
        from io import BytesIO
        import urllib.request
        import traceback

        FreeCAD.Console.PrintMessage(f"Recomputing {obj.Label}...\n")
        
        source_code = ""

        if obj.SourceMode == "Frozen":
            FreeCAD.Console.PrintMessage(f"'{obj.Label}' is Frozen, skipping recompute.\n")
            return
        if obj.SourceMode == "URL":
            if not hasattr(obj, "CodeURL") or not obj.CodeURL:
                FreeCAD.Console.PrintWarning("SourceMode is URL, but CodeURL is empty or missing.\n")
                return
            try:
                with urllib.request.urlopen(obj.CodeURL) as response:
                    source_code = response.read().decode('utf-8')
                
                if obj.CacheEnabled:
                    self._is_internal_change = True
                    try:
                        obj.CodeCache = source_code.splitlines()
                    finally:
                        self._is_internal_change = False
            except Exception:
                FreeCAD.Console.PrintError(f"Failed to fetch from URL: {obj.CodeURL}\n{traceback.format_exc()}\n")
                return
        
        elif obj.SourceMode == "Cache":
            if not obj.CodeCache:
                FreeCAD.Console.PrintWarning("SourceMode is Cache, but CodeCache is empty.\n")
                return
            source_code = "\n".join(obj.CodeCache)
        
        if not source_code:
            FreeCAD.Console.PrintError("No source code to execute.\n")
            return

        try:
            script_locals = {'cq': cq}
            exec(source_code, script_locals)
            result_obj = script_locals.get('result') or script_locals.get('show_object')
            
            if not result_obj:
                return 

            brep_stream = BytesIO()
            if isinstance(result_obj, (cq.Workplane, cq.Shape)):
                shape_to_export = result_obj.val() if isinstance(result_obj, cq.Workplane) else result_obj
                shape_to_export.exportBrep(brep_stream)
            else:
                FreeCAD.Console.PrintError(f"Result object type not supported: {type(result_obj).__name__}\n")
                return

            part_shape = Part.Shape()
            part_shape.importBrepFromString(brep_stream.getvalue().decode('utf-8'))
            obj.Shape = part_shape

        except Exception:
            FreeCAD.Console.PrintError(f"Error executing script for {obj.Label}:\n{traceback.format_exc()}\n")
            
    def onChanged(self, obj, prop):
        """
        A gatekeeper that handles property changes intelligently. It now
        automatically switches to 'Cache' mode if the CodeCache is edited.
        """
        from urllib.parse import urlparse
        
        if prop == "CodeCache":
            if self._is_internal_change:
                return 

            if obj.SourceMode != "Cache":
                FreeCAD.Console.PrintMessage("CodeCache edited, automatically switching SourceMode to 'Cache'.\n")
                obj.SourceMode = "Cache" 
            else:
                self.execute(obj)
            return  
        
        if prop == "SourceMode":
            self.execute(obj)
            return
        
        if prop == "CodeURL" and obj.SourceMode == "URL":
            if not hasattr(obj, "CodeURL"):
                 return
            url = obj.CodeURL
            try:
                parsed = urlparse(url)
                if parsed.scheme in ['http', 'https', 'file'] and parsed.path.endswith('.py'):
                    self.execute(obj)
            except Exception:
                pass  


class CadQueryFeatureViewProvider:
    """Controls how the CadQueryFeature object appears in the GUI."""
    
    def __init__(self, vobj):
        """Called when the ViewObject is created."""
        FreeCAD.Console.PrintMessage(f"ViewProvider __init__ called for object: {vobj.Object.Label}\n")
        # --- Corrected: Assign self to the proxy ---
        vobj.Proxy = self 
    
    def getIcon(self):
        """Returns the absolute path to the icon for the Tree View."""
        icon_path = os.path.join(ICON_PATH, "CQ_Logo.svg")
        if not os.path.exists(icon_path):
             FreeCAD.Console.PrintWarning(f"getIcon: Icon file not found at path: {icon_path}\n")
        FreeCAD.Console.PrintMessage(f"getIcon called! Returning path: {icon_path}\n")
        return icon_path
    
    def getCustomMenus(self):
        """Returns a list of context menu items."""
        return [{
            'text': "Edit CadQuery Code",
            'command': "CQ_EditCode" 
        }]

