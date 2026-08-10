# cq_utils.py
import FreeCAD

# --- Use the FreeCAD module itself to store the shared state ---
# Initialize the set only if it doesn't exist
if not hasattr(FreeCAD, "_cq_DOCUMENTS_CHECKED_ON_LOAD"):
    FreeCAD._cq_DOCUMENTS_CHECKED_ON_LOAD = set()


def document_key(doc):
    """Stable identity for a document's security clearance.

    Keyed on Uid rather than Name. Names are derived from the filename and are
    RECYCLED: clear a document called 'F1Spinner', close it, and the next
    document to open under that name inherited the clearance --
    _checkAndFreezeFeatures skipped the freeze and is_safe_to_execute returned
    True, so a freshly downloaded file with a familiar name executed its
    embedded URL on load. A Uid is minted per document and is not reused, so a
    stale entry can no longer clear an unrelated file.

    Falls back to Name if a document somehow has no Uid, which is no worse than
    the previous behaviour.
    """
    if doc is None:
        return None
    return getattr(doc, "Uid", None) or getattr(doc, "Name", None)


def mark_document_checked(doc_key):
    """Records that a document has been through the security check."""
    if not doc_key:
        return
    if hasattr(FreeCAD, "_cq_DOCUMENTS_CHECKED_ON_LOAD"):
        FreeCAD._cq_DOCUMENTS_CHECKED_ON_LOAD.add(doc_key)
    else:
        FreeCAD.Console.PrintError("Failed to mark document checked: Shared state set not found.\n")


def unmark_document_checked(doc_key):
    """Forgets a document's clearance, so a reopened file is checked again.

    Not load-bearing for security now that clearances are keyed on Uid -- it
    only keeps the set from growing for the life of the session -- so it is
    safe for this to be missed when a document closes.
    """
    if not doc_key:
        return
    if hasattr(FreeCAD, "_cq_DOCUMENTS_CHECKED_ON_LOAD"):
        FreeCAD._cq_DOCUMENTS_CHECKED_ON_LOAD.discard(doc_key)


def is_safe_to_execute(obj):
    """Checks if the document has been processed by the security observer using shared state."""
    # Allow execution if GUI not up or document link broken
    if not FreeCAD.GuiUp or not hasattr(obj, "Document") or not obj.Document:
        return True

    if hasattr(FreeCAD, "_cq_DOCUMENTS_CHECKED_ON_LOAD"):
        return document_key(obj.Document) in FreeCAD._cq_DOCUMENTS_CHECKED_ON_LOAD

    # If state is missing we cannot tell whether this document was checked.
    # Refuse rather than assume.
    FreeCAD.Console.PrintWarning("Could not find shared security state set. Assuming unsafe.\n")
    return False


def get_checked_documents_set():
    """Provides read-only access for debugging if needed."""
    return getattr(FreeCAD, "_cq_DOCUMENTS_CHECKED_ON_LOAD", set())
