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

def install_patch_with_link(target_filename, target_object_name):
    """
    Finds an editor by its MDI window title, links it to a specific
    CadQuery object via a custom property, and patches its save method.
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
    editor_sub_window.setProperty("targetTempFilename", target_filename)

    # Find the PythonEditor view object
    python_editor_view = None
    for view in FreeCADGui.ActiveDocument.ActiveView.getViews():
        # The view's document name should match our temp file
        if hasattr(view, 'fileName') and view.fileName() == target_filename:
            python_editor_view = view
            break
    
    # Alternative: try to get it from the subwindow's widget
    if not python_editor_view:
        widget = editor_sub_window.widget()
        if hasattr(widget, 'view'):
            python_editor_view = widget.view
        elif hasattr(widget, 'getView'):
            python_editor_view = widget.getView()
    
    if not python_editor_view:
        FreeCAD.Console.PrintWarning(f"Could not find PythonEditor view for '{target_filename}'. Falling back to close-only monitoring.\n")
        # Install close event filter as fallback
        install_close_event_filter(editor_sub_window, editor_widget, target_filename)
        return

    # Store the original save method
    original_save = python_editor_view.save if hasattr(python_editor_view, 'save') else None
    
    if not original_save:
        FreeCAD.Console.PrintWarning(f"PythonEditor view has no 'save' method. Falling back to close-only monitoring.\n")
        install_close_event_filter(editor_sub_window, editor_widget, target_filename)
        return

    # Define our custom save method
    def custom_save():
        """Custom save that updates the CadQuery object and calls original save."""
        FreeCAD.Console.PrintMessage(f"Custom save triggered for CQ editor!\n")
        
        # Get the object name from the window property
        obj_name = editor_sub_window.property("targetCQObjectName")
        if obj_name:
            doc = FreeCAD.ActiveDocument
            if doc:
                target_obj = doc.getObject(obj_name)
                if target_obj:
                    source_code = editor_widget.toPlainText()
                    target_obj.CodeCache = source_code.splitlines()
                    target_obj.recompute()
                    FreeCAD.Console.PrintMessage(f"Updated and recomputed '{target_obj.Label}' from save.\n")
        
        # Call the original save method
        return original_save()
    
    # Replace the save method
    python_editor_view.save = custom_save
    
    # Store reference to prevent garbage collection and allow cleanup
    _installed_patches[target_filename] = {
        'view': python_editor_view,
        'original_save': original_save,
        'sub_window': editor_sub_window,
        'editor_widget': editor_widget
    }
    
    # Also install close event filter for cleanup
    install_close_event_filter(editor_sub_window, editor_widget, target_filename)
    
    FreeCAD.Console.PrintMessage(f"Save method patched for '{target_object_name}' on editor '{target_filename}'.\n")


def install_close_event_filter(editor_sub_window, editor_widget, target_filename):
    """Install an event filter to handle window close events."""
    
    class CloseEventFilter(QtCore.QObject):
        def __init__(self, parent, sub_window, editor, filename):
            super().__init__(parent)
            self.sub_window = sub_window
            self.editor = editor
            self.filename = filename
            
        def eventFilter(self, watched_obj, event):
            if event.type() == QtCore.QEvent.Close and watched_obj is self.sub_window:
                self.on_editor_close()
            return super().eventFilter(watched_obj, event)
        
        def on_editor_close(self):
            """Handle editor close - update CadQuery object and cleanup."""
            obj_name = self.sub_window.property("targetCQObjectName")
            if obj_name:
                doc = FreeCAD.ActiveDocument
                if doc:
                    target_obj = doc.getObject(obj_name)
                    if target_obj:
                        source_code = self.editor.toPlainText()
                        target_obj.CodeCache = source_code.splitlines()
                        target_obj.recompute()
                        FreeCAD.Console.PrintMessage(f"Updated and recomputed '{target_obj.Label}' on close.\n")
            
            # Cleanup
            if self.filename in _installed_patches:
                patch_info = _installed_patches[self.filename]
                # Restore original save method if we patched it
                if 'view' in patch_info and 'original_save' in patch_info:
                    try:
                        patch_info['view'].save = patch_info['original_save']
                    except:
                        pass
                del _installed_patches[self.filename]
            
            # Remove temp file
            try:
                if os.path.exists(self.filename):
                    os.remove(self.filename)
                    FreeCAD.Console.PrintMessage(f"Removed temp file: {self.filename}\n")
            except OSError as e:
                FreeCAD.Console.PrintError(f"Error removing temp file: {e}\n")
    
    close_filter = CloseEventFilter(editor_sub_window, editor_sub_window, editor_widget, target_filename)
    editor_sub_window.installEventFilter(close_filter)
    
    # Store to prevent garbage collection
    if target_filename not in _installed_patches:
        _installed_patches[target_filename] = {}
    _installed_patches[target_filename]['close_filter'] = close_filter


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
    
    # Now that the file is open, find its window and install our patch
    install_patch_with_link(temp_path, obj.Name)
