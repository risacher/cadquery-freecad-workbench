# (c) 2014-2025 CadQuery Developers

"""
CadQuery GUI init module for FreeCAD
"""

import FreeCAD, FreeCADGui, Part
from CQGui.Command import (CadQueryHelp,
                           CadQueryClearOutput,
                           CadQueryStableInstall,
                           CadQueryUnstableInstall,
                           CadQueryCreateFeature,
                           EditCQCodeCmd,
                           Build123DInstall)

# --- 1. Define the observer class at the top level ---
class GlobalDocumentObserver:
    """A global observer to handle security for all loaded documents."""

    def slotCreatedDocument(self, doc):
        """Called by FreeCAD when any document is created or opened. This is TOO EARLY to check proxies."""
        # Instead of checking now, we start a short timer.
        # This gives FreeCAD time to finish restoring the Python proxies.
        try:
            from PySide6 import QtCore
        except ImportError:
            from PySide2 import QtCore
        QtCore.QTimer.singleShot(100, lambda: self._checkAndFreezeFeatures(doc.Document.Name))

    def _checkAndFreezeFeatures(self, doc_name):
        """This method runs after a short delay, when proxies are guaranteed to exist."""
        doc = FreeCAD.getDocument(doc_name)
        if not doc: return

        FreeCAD.Console.PrintMessage(f"Checking document '{doc.Label}' for CadQuery features...\n")
        features_to_freeze = []
        
        for obj in doc.Objects:
            # This check will now succeed
            if hasattr(obj, "Proxy") and hasattr(obj.Proxy, 'Type') and obj.Proxy.Type == 'CadQueryFeature':
                if obj.SourceMode != "Frozen":
                    obj.SourceMode = "Frozen"
                    features_to_freeze.append(obj.Label)

        if features_to_freeze:
            FreeCAD.Console.PrintWarning(f"For security, the following CadQuery features were set to 'Frozen' mode on load: {', '.join(features_to_freeze)}\n")
            FreeCAD.Console.PrintWarning("To re-enable them, select the object and change its SourceMode from 'Frozen' to 'URL' or 'Cache'.\n")

class CadQueryWorkbench (Workbench):
    """CadQuery workbench for FreeCAD"""

    MenuText = "CadQuery"
    ToolTip = "CadQuery workbench"

    def Initialize(self):
        """Called once when FreeCAD starts. Sets up menus and toolbars."""
        self.appendMenu('CadQuery', ['CadQueryClearOutput'])
        self.appendMenu(['CadQuery', 'Install'], ["CadQueryStableInstall",
                                                  "CadQueryUnstableInstall",
                                                  "Build123DInstall"])
        self.appendMenu('CadQuery', ['CadQueryHelp'])
        
        self.parametric_tools = ["CadQueryCreateFeature", "EditCQCode"]
        self.appendToolbar("CadQuery Parametric", self.parametric_tools)
        self.appendMenu("CadQuery", self.parametric_tools)

    # --- 2. Remove the observer logic from Activated() and Deactivated() ---
    # They are no longer needed for this task.
    def Activated(self):
        pass

    def Deactivated(self):
        pass

# --- 3. Register all commands and the workbench ---
FreeCADGui.addCommand('CadQueryStableInstall', CadQueryStableInstall())
FreeCADGui.addCommand('CadQueryUnstableInstall', CadQueryUnstableInstall())
FreeCADGui.addCommand('CadQueryCreateFeature', CadQueryCreateFeature())
FreeCADGui.addCommand('Build123DInstall', Build123DInstall())
FreeCADGui.addCommand('CadQueryClearOutput', CadQueryClearOutput())
FreeCADGui.addCommand('CadQueryHelp', CadQueryHelp())
FreeCADGui.addCommand('EditCQCode', EditCQCodeCmd())
FreeCADGui.addWorkbench(CadQueryWorkbench())

# --- 4. Create and register a single, permanent instance of the observer ---
# This code runs once when the module is loaded by FreeCAD, ensuring the
# observer is always active.
FreeCAD.Console.PrintMessage("Installed security documentObserver\n")
global_cq_security_observer = GlobalDocumentObserver()
FreeCADGui.addDocumentObserver(global_cq_security_observer)
