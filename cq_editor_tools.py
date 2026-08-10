# In a new file: cq_editor_tools.py

# --- Version-agnostic PySide import block ---
try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

import FreeCAD, FreeCADGui
import tempfile
import os

# --- Globals: Use a dictionary to track multiple patched editors ---
_installed_patches = {}

def install_patch_with_link(target_filename, target_object_name, target_doc_name):
    """
    Finds an editor by its MDI window title, links it to a specific
    CadQuery object via a custom property, and installs event monitoring.

    The document name is recorded alongside the object name: resolving the
    target through FreeCAD.ActiveDocument instead meant that switching
    documents with an editor open wrote the code into whatever happened to be
    active, or silently nowhere.
    """
    global _installed_patches

    main_window = FreeCADGui.getMainWindow()
    mdi_area = main_window.findChild(QtWidgets.QMdiArea)
    if not mdi_area: return

    editor_sub_window = None
    for sub_window in mdi_area.subWindowList():
        if target_filename in sub_window.windowTitle():
            editor_sub_window = sub_window
            break

    if not editor_sub_window:
        FreeCAD.Console.PrintWarning(f"Could not find a sub-window for '{target_filename}'.\n")
        return

    editor_widget = editor_sub_window.widget().findChild(QtWidgets.QPlainTextEdit)
    if not editor_widget: return
    
    # Store the object's unique name as a custom property on the editor window
    editor_sub_window.setProperty("targetCQObjectName", target_object_name)
    editor_sub_window.setProperty("targetCQDocName", target_doc_name)
    editor_sub_window.setProperty("targetTempFilename", target_filename)

    # Install our custom event filter that monitors both save and close
    install_editor_monitor(editor_sub_window, editor_widget, target_filename)
    
    FreeCAD.Console.PrintMessage(f"Editor monitor installed for '{target_object_name}' on editor '{target_filename}'.\n")


def install_editor_monitor(editor_sub_window, editor_widget, target_filename):
    """Install an event filter to handle save shortcuts and window close events."""
    
    class EditorMonitor(QtCore.QObject):
        def __init__(self, parent, sub_window, editor, filename):
            super().__init__(parent)
            self.sub_window = sub_window
            self.editor = editor
            self.filename = filename
            # Seed from the file, not the widget, so the first poll compares
            # like with like. They agree at install time -- the file was just
            # written from CodeCache -- but only the file is authoritative.
            self.last_saved_content = self._read_file()
            if self.last_saved_content is None:
                self.last_saved_content = editor.toPlainText()


            # Install a timer to periodically check if file was saved
            self.check_timer = QtCore.QTimer(self)
            self.check_timer.timeout.connect(self.check_for_save)
            self.check_timer.start(500)  # Check every 500ms
            
        def eventFilter(self, watched_obj, event):
            # Handle window close
            if event.type() == QtCore.QEvent.Close and watched_obj is self.sub_window:
                self.on_editor_close()
            return super().eventFilter(watched_obj, event)
        
        def _read_file(self):
            """Current contents of the temp file, or None if unreadable."""
            try:
                if os.path.exists(self.filename):
                    with open(self.filename, 'r', encoding='utf-8') as f:
                        return f.read()
            except OSError as e:
                FreeCAD.Console.PrintError(f"Error reading CQ editor file: {e}\n")
            return None

        def check_for_save(self):
            """Periodically check if the editor content has been saved to disk."""
            try:
                self._check_for_save()
            except Exception as e:
                # This runs from a Qt slot every 500 ms. If the sub-window's C++
                # side has been destroyed, property() raises RuntimeError, and
                # an unguarded body would then raise on every single tick.
                # A monitor that cannot read its own window is finished, so stop
                # rather than spam; on_editor_close still runs via the event
                # filter if the close event arrives.
                FreeCAD.Console.PrintError(f"Error checking for save: {e}\n")
                self.check_timer.stop()

        def _check_for_save(self):
            file_content = self._read_file()
            if file_content is None or file_content == self.last_saved_content:
                return
            FreeCAD.Console.PrintMessage("Detected save of CQ editor file.\n")
            # Push what is ON DISK. This previously detected the change by
            # reading the file and then pushed self.editor.toPlainText()
            # instead, so an edit made to the temp file outside the widget was
            # noticed and then immediately discarded.
            self.last_saved_content = file_content
            self.update_cadquery_object(file_content)

        def _target_object(self):
            """Resolve the linked feature via its OWN document, not the active one."""
            obj_name = self.sub_window.property("targetCQObjectName")
            doc_name = self.sub_window.property("targetCQDocName")
            if not obj_name:
                return None
            doc = None
            if doc_name:
                doc = FreeCAD.listDocuments().get(doc_name)
                if doc is None:
                    FreeCAD.Console.PrintWarning(
                        f"Document '{doc_name}' for this CQ editor is no longer open; "
                        f"changes will not be applied.\n")
                    return None
            else:
                doc = FreeCAD.ActiveDocument      # links made before this field existed
            return doc.getObject(obj_name) if doc else None

        def update_cadquery_object(self, source_code):
            """Update the CadQuery object from the given source text."""
            target_obj = self._target_object()
            if not target_obj:
                return
            target_obj.CodeCache = source_code.splitlines()
            target_obj.recompute()
            FreeCAD.Console.PrintMessage(f"Updated and recomputed '{target_obj.Label}'.\n")


        def on_editor_close(self):
            """Handle editor close - update CadQuery object and cleanup."""
            # Stop the timer
            self.check_timer.stop()

            # Final update on close. Deliberately the WIDGET text, not the file:
            # the temp file is about to be deleted, so this is the last chance
            # to capture edits the user never saved.
            self.update_cadquery_object(self.editor.toPlainText())


            # Cleanup
            if self.filename in _installed_patches:
                del _installed_patches[self.filename]
            
            # Remove temp file
            try:
                if os.path.exists(self.filename):
                    os.remove(self.filename)
                    FreeCAD.Console.PrintMessage(f"Removed temp file: {self.filename}\n")
            except OSError as e:
                FreeCAD.Console.PrintError(f"Error removing temp file: {e}\n")
    
    monitor = EditorMonitor(editor_sub_window, editor_sub_window, editor_widget, target_filename)
    editor_sub_window.installEventFilter(monitor)
    
    # Store to prevent garbage collection
    _installed_patches[target_filename] = {
        'monitor': monitor,
        'sub_window': editor_sub_window,
        'editor_widget': editor_widget
    }


def launch_editor_for_feature(obj):
    """
    Writes a feature's CodeCache to a temp file and opens it in the editor.
    """
    if not obj or not hasattr(obj, "CodeCache"):
        FreeCAD.Console.PrintWarning("Please provide a valid CadQuery feature object.\n")
        return

    code = "\n".join(obj.CodeCache)
    
    # Create a temporary file that won't be deleted on close
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as tf:
        tf.write(code)
        temp_path = tf.name
    
    FreeCAD.Console.PrintMessage(f"Opening temp file for '{obj.Label}': {temp_path}\n")
    FreeCADGui.open(temp_path)
    
    # Use a short delay to ensure the editor window is fully created
    doc_name = obj.Document.Name if getattr(obj, "Document", None) else None

    def delayed_patch():
        install_patch_with_link(temp_path, obj.Name, doc_name)
    
    QtCore.QTimer.singleShot(100, delayed_patch)
