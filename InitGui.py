"""
CadQuery GUI init module for FreeCAD
"""

import FreeCAD, FreeCADGui, Part
import traceback
# functools and QtCore are imported locally where needed
# cq_utils is also imported locally where needed

from CQGui.Command import (CadQueryHelp,
                           CadQueryClearOutput,
                           CadQueryStableInstall,
                           CadQueryUnstableInstall,
                           CadQueryCreateFeature,
                           EditCQCodeCmd,
                           Build123DInstall)

# --- Define the observer class at the top level ---
class GlobalDocumentObserver:
    """A global observer to handle security for all loaded documents."""

    def slotCreatedDocument(self, doc):
        """Called by FreeCAD when any document is created or opened."""
        cq_utils = None # Define cq_utils variable in this scope

        try:
            # Import necessary modules locally
            try:
                from PySide6 import QtCore
            except ImportError:
                from PySide2 import QtCore
            import functools
            # --- MODIFIED: Import cq_utils locally ---
            try:
                import cq_utils
            except ImportError:
                 FreeCAD.Console.PrintError("FATAL: Could not import cq_utils inside observer. Security checks will fail.\n")
                 # Define dummy functions if import fails
                 def mark_document_checked(doc_name): pass
                 def get_checked_documents_set(): return set()
                 cq_utils = type('obj', (object,), {
                     'mark_document_checked': mark_document_checked,
                     'get_checked_documents_set': get_checked_documents_set
                 })()

        except ImportError as e:
            FreeCAD.Console.PrintError(f"Core import failed in DocumentObserver ({e}). Security timer will not run.\n")
            # Mark as checked immediately if timer cannot run
            if hasattr(doc, "Document") and doc.Document and cq_utils:
                 cq_utils.mark_document_checked(doc.Document.Name)
            return

        # Use App.Document.Name which is the unique identifier
        if hasattr(doc, "Document") and doc.Document:
             doc_name = doc.Document.Name
             # Check using cq_utils' set via its getter
             # Ensure cq_utils was successfully imported before using it
             if cq_utils and doc_name not in cq_utils.get_checked_documents_set():
                 callback = functools.partial(self._checkAndFreezeFeatures, doc_name)
                 QtCore.QTimer.singleShot(300, callback) # Increased delay slightly
             # else: # Verbose logging
             #     if cq_utils:
             #          FreeCAD.Console.PrintMessage(f"Document '{doc_name}' already checked or cq_utils missing, skipping timer.\n")

        else:
             FreeCAD.Console.PrintWarning("slotCreatedDocument received Gui.Document without App.Document link, skipping security check timer.\n")


    def _checkAndFreezeFeatures(self, doc_name):
        """This method runs after a short delay, ensuring proxies are likely attached."""
        # --- MODIFIED: Import cq_utils locally here too ---
        cq_utils = None
        try:
            import cq_utils
        except ImportError:
             FreeCAD.Console.PrintError("FATAL: Could not import cq_utils in timer callback. Cannot mark document checked.\n")
             return # Cannot proceed without utils

        # Check again using cq_utils getter
        if doc_name in cq_utils.get_checked_documents_set():
             return

        FreeCAD.Console.PrintMessage(f"Timer callback: Running security check for doc_name '{doc_name}'...\n")

        doc = FreeCAD.getDocument(doc_name)
        if not doc:
            FreeCAD.Console.PrintError(f"Timer callback: Could not get document '{doc_name}'.\n")
            return

        FreeCAD.Console.PrintMessage(f"Running security check for document '{doc.Label}'...\n")
        features_to_freeze = []
        found_cq_feature = False
        processed_ok = False # Flag to ensure we only add to set on success

        try:
            for obj in doc.Objects:
                proxy = getattr(obj, "Proxy", None)
                obj_type = getattr(proxy, "Type", None)

                if obj_type == 'CadQueryFeature':
                    found_cq_feature = True
                    if hasattr(obj, "SourceMode") and obj.SourceMode != "Frozen":
                        obj.SourceMode = "Frozen"
                        features_to_freeze.append(obj.Label)

            if features_to_freeze:
                FreeCAD.Console.PrintWarning(f"For security, the following CadQuery features were set to 'Frozen' mode on load: {', '.join(features_to_freeze)}\n")
                FreeCAD.Console.PrintWarning("To re-enable them, select the object and change its SourceMode from 'Frozen' to 'URL' or 'Cache'.\n")
            elif found_cq_feature:
                 FreeCAD.Console.PrintMessage("All CadQuery features in this document were already Frozen.\n")
            else:
                 FreeCAD.Console.PrintMessage("No CadQuery features found in this document.\n")

            processed_ok = True # Mark processing as successful

        except Exception as e:
            FreeCAD.Console.PrintError(f"Error during security check for '{doc_name}': {e}\n{traceback.format_exc()}\n")

        finally:
             if processed_ok and cq_utils: # Ensure cq_utils exists before using
                 # Use cq_utils to mark checked
                 cq_utils.mark_document_checked(doc_name)
                 FreeCAD.Console.PrintMessage(f"Document '{doc.Label}' security check complete and marked.\n")
             elif not processed_ok:
                 FreeCAD.Console.PrintError(f"Document '{doc_name}' security check failed. Execution may remain blocked.\n")


class CadQueryWorkbench (Workbench):
    """CadQuery workbench for FreeCAD"""
    MenuText = "CadQuery"
    ToolTip = "CadQuery workbench"

    def Initialize(self):
        # --- Import Workbench if needed ---
        try:
            from FreeCADGui import Workbench
        except ImportError:
            pass # Assume globally available

        self.appendMenu('CadQuery', ['CadQueryClearOutput'])
        self.appendMenu(['CadQuery', 'Install'], ["CadQueryStableInstall",
                                                  "CadQueryUnstableInstall",
                                                  "Build123DInstall"])
        self.appendMenu('CadQuery', ['CadQueryHelp'])

        self.parametric_tools = ["CadQueryCreateFeature", "EditCQCode"]
        self.appendToolbar("CadQuery Parametric", self.parametric_tools)
        self.appendMenu("CadQuery", self.parametric_tools)

    def Activated(self):
        pass

    def Deactivated(self):
        pass

# --- Register commands and workbench ---
# --- Ensure Workbench is defined before use ---
try:
    from FreeCADGui import Workbench
except ImportError:
    pass

FreeCADGui.addCommand('CadQueryStableInstall', CadQueryStableInstall())
FreeCADGui.addCommand('CadQueryUnstableInstall', CadQueryUnstableInstall())
FreeCADGui.addCommand('CadQueryCreateFeature', CadQueryCreateFeature())
FreeCADGui.addCommand('Build123DInstall', Build123DInstall())
FreeCADGui.addCommand('CadQueryClearOutput', CadQueryClearOutput())
FreeCADGui.addCommand('CadQueryHelp', CadQueryHelp())
FreeCADGui.addCommand('EditCQCode', EditCQCodeCmd())
FreeCADGui.addWorkbench(CadQueryWorkbench())

# --- Register the global observer ---
if not hasattr(FreeCAD, "_cq_observer_registered"):
    global_cq_security_observer = GlobalDocumentObserver()
    FreeCADGui.addDocumentObserver(global_cq_security_observer)
    FreeCAD._cq_observer_registered = True
    FreeCAD.Console.PrintMessage("✅ Global CadQuery security observer registered.\n")
else:
    FreeCAD.Console.PrintMessage("ℹ️ Global CadQuery security observer already registered.\n")

