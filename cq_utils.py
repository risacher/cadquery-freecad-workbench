# cq_utils.py
import FreeCAD

# --- Use the FreeCAD module itself to store the shared state ---
# Initialize the set only if it doesn't exist
if not hasattr(FreeCAD, "_cq_DOCUMENTS_CHECKED_ON_LOAD"):
    FreeCAD._cq_DOCUMENTS_CHECKED_ON_LOAD = set()

def mark_document_checked(doc_name):
    """Adds a document name to the shared set on the FreeCAD module."""
    if hasattr(FreeCAD, "_cq_DOCUMENTS_CHECKED_ON_LOAD"):
        FreeCAD._cq_DOCUMENTS_CHECKED_ON_LOAD.add(doc_name)
        # Optional: Log which documents are being marked
        # FreeCAD.Console.PrintMessage(f"Marked document '{doc_name}' as security checked in FreeCAD state.\n")
    else:
        FreeCAD.Console.PrintError("Failed to mark document checked: Shared state set not found.\n")


def is_safe_to_execute(obj):
    """Checks if the document has been processed by the security observer using shared state."""
    # Allow execution if GUI not up or document link broken
    if not FreeCAD.GuiUp or not hasattr(obj, "Document") or not obj.Document:
        return True

    # Check if the document NAME is in the shared set on the FreeCAD module
    if hasattr(FreeCAD, "_cq_DOCUMENTS_CHECKED_ON_LOAD"):
        doc_name = obj.Document.Name
        is_safe = doc_name in FreeCAD._cq_DOCUMENTS_CHECKED_ON_LOAD
        # Optional: Log the check result
        # FreeCAD.Console.PrintMessage(f"is_safe_to_execute check for '{doc_name}': {is_safe}\n")
        return is_safe
    else:
        # If state missing, assume unsafe? Or allow? Let's be cautious.
        FreeCAD.Console.PrintWarning("Could not find shared security state set. Assuming unsafe.\n")
        return False

def get_checked_documents_set():
    """Provides read-only access for debugging if needed."""
    return getattr(FreeCAD, "_cq_DOCUMENTS_CHECKED_ON_LOAD", set())

