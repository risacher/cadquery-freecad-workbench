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
_installed_filters = {}

def install_patch_with_link(target_filename, target_object_name):
    """
    Finds an editor by its MDI window title, links it to a specific
    CadQuery object via a custom property, and installs the event filter.
    """
    global _installed_filters

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
    
    # --- This is the key to the new robust design ---
    # Store the object's unique name as a custom property on its editor window.
    editor_sub_window.setProperty("targetCQObjectName", target_object_name)

    # --- Define the Event Filter ---
    class EditorEventFilter(QtCore.QObject):
        def eventFilter(self, watched_obj, event):
            is_close_event = (event.type() == QtCore.QEvent.Close and watched_obj is editor_sub_window)
            is_save_event = (event.type() == QtCore.QEvent.KeyPress and 
                             watched_obj is editor_widget and
                             event.key() == QtCore.Qt.Key_S and 
                             event.modifiers() == QtCore.Qt.ControlModifier)
            
            if is_save_event or is_close_event:
                self.update_cadquery_object(editor_sub_window, editor_widget)
                if is_save_event:
                    event.accept()
                    return True # Stop the event from propagating further

            return super().eventFilter(watched_obj, event)

        def update_cadquery_object(self, sub_window, editor):
            # --- Retrieve the link from the custom property ---
            obj_name = sub_window.property("targetCQObjectName")
            if not obj_name: return

            doc = FreeCAD.ActiveDocument
            target_obj = doc.getObject(obj_name)
            if not target_obj: return

            source_code = editor.toPlainText()
            target_obj.CodeCache = source_code.splitlines()
            target_obj.recompute()
            
            # --- Cleanup ---
            # Remove the temp file and our filter from the global dict
            if target_filename in _installed_filters:
                try:
                    os.remove(target_filename)
                    FreeCAD.Console.PrintMessage(f"Removed temp file: {target_filename}\n")
                except OSError as e:
                    FreeCAD.Console.PrintError(f"Error removing temp file: {e}\n")
                del _installed_filters[target_filename]

            # FreeCAD.Console.PrintMessage(f"Updated and recomputed '{target_obj.Label}' via linked property.\n")

    # Prevent the filter from being garbage-collected by storing it globally
    _installed_filters[target_filename] = EditorEventFilter(editor_sub_window)
    
    editor_sub_window.installEventFilter(_installed_filters[target_filename])
    editor_widget.installEventFilter(_installed_filters[target_filename])
    
    # FreeCAD.Console.PrintMessage(f"Patch installed for '{target_object_name}' on editor '{target_filename}'.\n")

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

