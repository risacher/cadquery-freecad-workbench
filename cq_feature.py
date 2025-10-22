# In a new file, for example, cq_feature.py

import FreeCAD
import cadquery as cq
import urllib.request

class CadQueryFeature:
    """The Python Proxy class that gives our object its intelligence."""

class CadQueryFeature:
    """The Python Proxy class that gives our object its intelligence."""

    def __init__(self, obj):
        """This is called when the object is created."""
        obj.Proxy = self
        self.Type = 'CadQueryFeature'
        
        # --- MODIFIED PROPERTIES ---
        # Add the new SourceMode property
        obj.addProperty("App::PropertyEnumeration", "SourceMode", "CadQuery", "The source of the script to execute").SourceMode = ["URL", "Cache"]
        obj.addProperty("App::PropertyString", "CodeURL", "CadQuery", "URL to the source .py file").CodeURL = ""
        obj.addProperty("App::PropertyBool", "CacheEnabled", "CadQuery", "Update the cache when computing from URL").CacheEnabled = True
        obj.addProperty("App::PropertyStringList", "CodeCache", "CadQuery", "A local cache of the source code")

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

        # --- NEW LOGIC: Get source code based on the mode ---
        if obj.SourceMode == "URL":
            if not obj.CodeURL:
                FreeCAD.Console.PrintWarning("SourceMode is URL, but CodeURL is empty.\n")
                return
            try:
                with urllib.request.urlopen(obj.CodeURL) as response:
                    source_code = response.read().decode('utf-8')
                # If caching is on, update the cache
                if obj.CacheEnabled:
                    obj.CodeCache = source_code.splitlines()
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

        # --- The rest of the execution logic remains the same ---
        try:
            script_locals = {'cq': cq}
            exec(source_code, script_locals)
            result_obj = script_locals.get('result') or script_locals.get('show_object')
            
            if not result_obj:
                return # Script ran but produced no result

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
        #FreeCAD.Console.PrintMessage(f"onChanged fired! Prop: {prop}\n")
        from urllib.parse import urlparse
        
        # CASE 1: The user manually edits the CodeCache property.
        if prop == "CodeCache":
            # If the object is in URL mode, just switch it to Cache mode.
            # This will fire another onChanged event for "SourceMode",
            # which will then correctly call self.execute(obj).
            if obj.SourceMode != "Cache":
                FreeCAD.Console.PrintMessage("CodeCache edited, automatically switching SourceMode to 'Cache'.\n")
                obj.SourceMode = "Cache" # This should now force the GUI to update            obj.SourceMode = "Cache"
            else:
                # If already in Cache mode, the user expects a recompute.
                self.execute(obj)
                return  # We've handled this event.
            
            # CASE 2: The user changes the SourceMode dropdown. This is now the
            # single point of truth for recomputing after a mode switch.
            if prop == "SourceMode":
                self.execute(obj)
                return
            
            # CASE 3: The user is typing in the CodeURL field.
            if prop == "CodeURL" and obj.SourceMode == "URL":
                url = obj.CodeURL
                try:
                    # Validate the URL to avoid recomputing on every keystroke.
                    parsed = urlparse(url)
                    if parsed.scheme in ['http', 'https', 'file'] and parsed.path.endswith('.py'):
                        self.execute(obj)
                except Exception:
                    pass  # Ignore incomplete/malformed URLs.
