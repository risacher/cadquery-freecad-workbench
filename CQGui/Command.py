# -*- coding: utf-8 -*-
# (c) 2014-2025 CadQuery Developers

"""Adds all of the commands that are used for the menus of the CadQuery module"""

import FreeCAD
import FreeCADGui
from PySide import QtGui
from CQGui.HelpDialog import HelpDialog

import cq_feature
import cq_editor_tools
import os
import sys
import subprocess

EDIT_SESSION = {}


def _pip(*args):
    """Run pip against the interpreter FreeCAD is actually using.

    These commands used to shell out to bare "python", which resolves through
    PATH. On a typical Linux box that is the system interpreter -- here
    /usr/bin/python is 3.12 while FreeCAD embeds 3.11 -- so packages landed in
    a site-packages FreeCAD never reads and the install appeared to succeed
    while changing nothing.

    sys.executable is not a drop-in substitute either: in an AppImage build it
    is the freecad binary itself, and there is no python3 anywhere on the
    prefix to invoke. pip is importable in-process though, so when we have no
    interpreter to call, drive it here instead.

    Note pip decides for itself where to install; under the read-only AppImage
    mount it falls back to a --user install, which is why ~/.local/lib/python3.11
    is where cadquery already lives.
    """
    args = [str(a) for a in args]
    exe = sys.executable or ""

    if os.path.basename(exe).lower().startswith("python"):
        print("$ " + " ".join([exe, "-m", "pip"] + args))
        return subprocess.run([exe, "-m", "pip"] + args).returncode

    print("$ <FreeCAD's embedded python> -m pip " + " ".join(args))
    import runpy
    saved_argv = sys.argv
    try:
        sys.argv = ["pip"] + args
        runpy.run_module("pip", run_name="__main__")
        return 0
    except SystemExit as e:                 # pip always exits
        return e.code if isinstance(e.code, int) else 0
    finally:
        sys.argv = saved_argv


def _report(name, codes):
    """Say whether an install actually worked, rather than always claiming it did."""
    if any(codes):
        print(f"{name} install FAILED (pip exit codes {codes}). Nothing was changed "
              f"that you can rely on; see the messages above.")
    else:
        print(f"{name} has been installed! Please restart FreeCAD.")

GUI_PATH = os.path.dirname(__file__)
# This builds the full path to your icons folder
ICON_PATH = os.path.join(GUI_PATH, "icons")

class CadQueryCreateFeature:
    """Command to create a parametric CadQuery Feature."""
    
    def GetResources(self):
        return {"MenuText": "Create CadQuery Feature",
                "Accel": "",
                "ToolTip": "Creates a CadQuery Object",
                "Pixmap": os.path.join(ICON_PATH, "CQ_New.svg")}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        # 1. Create a generic container object
        obj = FreeCAD.ActiveDocument.addObject("Part::FeaturePython", "CadQuery_Feature")
        
        # 2. Attach our Python proxy class to it
        #    This is what gives it the custom icon, properties, and execute behavior.
        cq_feature.CadQueryFeature(obj)
        
        # 3. Prompt user for the initial URL (optional, can be set later)
        # ... dialog logic ...
        
        # 4. Finalize
        if FreeCAD.GuiUp and hasattr(obj, "ViewObject"):
            try:
                obj.ViewObject.Proxy = cq_feature.CadQueryFeatureViewProvider(obj.ViewObject)
                FreeCAD.Console.PrintMessage("ViewProvider attached successfully from Command.Activated.\n")
            except Exception as e:
                FreeCAD.Console.PrintError(f"Error attaching ViewProvider from Command.Activated: {e}\n")
        FreeCAD.ActiveDocument.recompute()

        
class CadQueryStableInstall:
    """
    Allows the user to easily attempt a manual install of the stable version of CadQuery
    """

    def GetResources(self):
        return {"MenuText": "Install CadQuery Stable",
                "Accel": "",
                "ToolTip": "Installs the stable version of CadQuery",
                "Pixmap": ":/icons/preferences-system.svg"}

    def IsActive(self):
        return True

    def Activated(self):
        print("Starting to install CadQuery stable...")
        # Unpinned: "stable" means the current stable release, not a version
        # frozen at the time this menu was written. The old pins were
        # cadquery==2.5.2 with cadquery-ocp==7.7.2, which by now DOWNGRADES a
        # working install, and drags OCP below what build123d needs.
        #
        # Resolve alongside build123d whenever it is present. The two share the
        # OCP binding -- build123d pulls cadquery-ocp-novtk, a second
        # distribution of the same OCP module -- so upgrading one behind the
        # other's back is exactly what left this machine with two OCP packagings
        # stacked on each other and nothing importable at all.
        targets = ["cadquery"]
        import importlib.util
        if importlib.util.find_spec("build123d") is not None:
            targets.append("build123d")
            print("build123d is installed; resolving both together.")
        codes = [_pip("install", "--upgrade", *targets)]
        _report("CadQuery stable", codes)


class CadQueryUnstableInstall:
    """
    Allows the user to easily attempt a manual install of the unstable version of CadQuery
    """

    def GetResources(self):
        return {"MenuText": "Install CadQuery Unstable",
                "Accel": "",
                "ToolTip": "Installs the unstable version of CadQuery",
                "Pixmap": ":/icons/preferences-system.svg"}

    def IsActive(self):
        return True

    def Activated(self):
        print("Starting to install CadQuery unstable...")
        _pip("uninstall", "-y", "vtk")
        _pip("uninstall", "-y", "cadquery-vtk")
        _pip("uninstall", "-y", "cadquery-ocp")
        codes = [_pip("install", "--upgrade", "vtk==9.3.1"),
                 _pip("install", "--upgrade", "cadquery-ocp==7.8.1.0"),
                 _pip("install", "--upgrade", "https://github.com/CadQuery/cadquery.git")]
        _report("CadQuery unstable", codes)


class Build123DInstall:
    """
    Allows the user to easily attempt a manual install of Build123D
    """

    def GetResources(self):
        return {"MenuText": "Install Build123d",
                "Accel": "",
                "ToolTip": "Installs Build123d",
                "Pixmap": ":/icons/preferences-system.svg"}

    def IsActive(self):
        return True

    def Activated(self):
        print("Starting to install Build123d...")
        # Install build123d AND cadquery in ONE pip invocation so the resolver
        # has to satisfy both at once.
        #
        # This used to install build123d and then force
        # cadquery-ocp==7.8.1.1.post1 in a separate command. cadquery 2.5.2
        # declares cadquery-ocp<7.8, so that pin quietly broke CadQuery -- and
        # worse, build123d depends on cadquery-ocp-NOVTK, a second
        # distribution of the same OCP module. Installing both left two OCP
        # packagings on top of each other and nothing imported at all:
        #   ImportError: libvtkWrappingPythonCore3.11-9.3.so: cannot open
        #   shared object file
        # Resolving them together instead lands a consistent set (verified:
        # cadquery 2.8.0 + cadquery-ocp 7.9.3.1.1 + build123d 0.11.1 + vtk
        # 9.6.2, "pip check" clean, both libraries importable).
        codes = [_pip("install", "--upgrade", "build123d", "cadquery")]
        _report("Build123d + CadQuery", codes)


class CadQueryClearOutput:
    """Allows the user to clear the reports view when it gets overwhelmed with output"""

    def GetResources(self):
        return {"MenuText": "Clear Output",
                "Accel": "Shift+Alt+C",
                "ToolTip": "Clears the script output from the Reports view",
                "Pixmap": ":/icons/button_invalid.svg"}

    def IsActive(self):
        return True

    def Activated(self):
        # Grab our main window so we can interact with it
        mw = FreeCADGui.getMainWindow()

        reportView = mw.findChild(QtGui.QDockWidget, "Report view")

        # Clear the view because it gets overwhelmed sometimes and won't scroll to the bottom
        reportView.widget().clear()


class CadQueryHelp:
    """Opens a help dialog, allowing the user to access documentation and information about CadQuery"""

    def GetResources(self):
        return {"MenuText": "Help",
                "Accel": "",
                "ToolTip": "Opens the Help dialog",
                "Pixmap": ":/icons/help-browser.svg"}

    def IsActive(self):
        return True

    def Activated(self):
        win = HelpDialog()

        win.exec_()

import tempfile
import os

class EditCQFeatureScriptCommand:
    """Checks out a feature's script to a temporary file and opens it for editing."""

    def GetResources(self):
        return {"MenuText": "Edit Script in Cache", "ToolTip": "Edit the selected feature's script in the editor."}

    def IsActive(self):
        sel = FreeCADGui.Selection.getSelection()
        return len(sel) == 1 and hasattr(sel[0], "Proxy") and sel[0].Proxy.Type == 'CadQueryFeature'

    def Activated(self):
        global EDIT_SESSION
        obj = FreeCADGui.Selection.getSelection()[0]
        
        # --- NEW: Automatically switch to Cache mode ---
        obj.SourceMode = "Cache"
        
        fd, temp_path = tempfile.mkstemp(suffix='.py', text=True)
        os.close(fd)

        # Use the cache as the source of truth
        if obj.CodeCache:
            with open(temp_path, 'w') as f:
                f.write("\n".join(obj.CodeCache))
        
        EDIT_SESSION['object_name'] = obj.Name
        EDIT_SESSION['temp_path'] = temp_path
        
        FreeCADGui.open(temp_path)
        FreeCAD.Console.PrintMessage(f"Switched '{obj.Label}' to Cache mode and opened script for editing.\n")


class UpdateCQFeatureFromEditorCommand:
    """Checks in the edited script from the temp file back to the object."""

    def GetResources(self):
        return {"MenuText": "Update Object from Editor", "ToolTip": "Updates the object with the code from the active editor tab."}

    def IsActive(self):
        return 'temp_path' in EDIT_SESSION

    def Activated(self):
        global EDIT_SESSION
        
        temp_path = EDIT_SESSION.get('temp_path')
        obj_name = EDIT_SESSION.get('object_name')

        if not temp_path or not obj_name:
            return
            
        obj = FreeCAD.ActiveDocument.getObject(obj_name)
        if not obj:
            EDIT_SESSION.clear()
            return

        # --- REVISED LOGIC ---
        try:
            # 1. Read the updated code from the temp file
            with open(temp_path, 'r') as f:
                updated_code = f.read()
            
            # 2. Update the object's property
            obj.CodeCache = updated_code.splitlines()
            
            # 3. Find and close the editor tab BEFORE deleting the file
            mw = FreeCADGui.getMainWindow()
            mdi_area = mw.findChild(QtGui.QMdiArea)
            for sub_window in mdi_area.subWindowList():
                if sub_window.windowFilePath() == temp_path:
                    sub_window.close()
                    break
            
            # 4. Now it's safe to delete the temp file
            os.remove(temp_path)

            FreeCAD.Console.PrintMessage(f"Updated '{obj.Label}' from script. Recomputing...\n")
        
        finally:
            # 5. Always clear the session and trigger a recompute
            EDIT_SESSION.clear()
            FreeCAD.ActiveDocument.recompute()
            
# In your workbench's command file, e.g., commands.py


class EditCQCodeCmd:
    """The command class for our new 'Edit Code' button."""

    def GetResources(self):
        """Icon and tooltip for the command."""
        return {
            "Pixmap": os.path.join(ICON_PATH, "CQ_Edit.svg"), # Your icon
            "MenuText": "Edit CadQuery Code",
            "ToolTip": "Opens the cached code for the selected object in an editor. Saving or closing will update the object."
        }

    def IsActive(self):
        """Enables the button only if a single CadQuery feature is selected."""
        sel = FreeCADGui.Selection.getSelection()
        if len(sel) != 1:
            return False
        # Check if the selected object is one of yours
        if hasattr(sel[0], "Proxy") and sel[0].Proxy.Type == 'CadQueryFeature':
            return True
        return False

    def Activated(self):
        """This is what runs when the button is clicked."""
        sel = FreeCADGui.Selection.getSelection()
        if self.IsActive():
            target_object = sel[0]
            # Call our new, robust function!
            cq_editor_tools.launch_editor_for_feature(target_object)

