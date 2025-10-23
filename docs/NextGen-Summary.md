# FreeCAD CadQuery Workbench Feature Development Summary

In October 2025, Dan Risacher (dan@risacher.org) prototyped this
update of the cadquery-freecad-workbench, which changes the user
experience pretty significantly.  Instead of using FreeCAD macros to
run cadquery scripts to generate geometry, which arguably breaks the
principle of encapsulation, the updated workbench supports CadQuery
Features inside a FreeCAD model that can generate 3D geometry from
code either located by URL (such as file:/// or https://) or from an
embedded cache inside the FreeCAD file.

To address significant security concerns related to execution of
(possibly untrusted) portable code, this updated
cadquery-freecad-workbench automatically "freezes" all such objects
whenever a FreeCAD model is loaded, requiring the user to manually
switch them back to "URL" or "Cache" mode before execution.

To facilitate parameterized models, the Workbench supports a
"Parameter Source" attribute, that can be either a VarSet or
Spreadsheet (in which case it imports all aliases) into the CadQuery
python environment. This allows CadQuery geometry to be parametrically
dependent on other FreeCAD features.


## Implemented Features:

* **Core Parametric Feature:** Created a `Part::FeaturePython` object to execute CadQuery scripts within FreeCAD.
* **Source Modes:** Implemented multiple ways to source the CadQuery script:
    * `URL`: Fetches the script from a web address.
    * `Cache`: Uses code stored directly within the object's `CodeCache` property.
    * `Frozen`: Disables script execution, preserving the existing shape (primarily for security).
* **Integrated Editor Link:**
    * Added an "Edit CadQuery Code" command accessible via a toolbar button and the object's right-click context menu (both with custom icons).
    * The command opens the object's cached code in FreeCAD's editor using a temporary file.
    * Implemented an event listener that automatically updates the object's `CodeCache` and triggers a recompute when the linked editor window is saved (`Ctrl+S`) or closed.
    * Ensured the editor is reliably linked to the specific object being edited, even if multiple editors are open or the user changes selection.
* **Security Observer:**
    * Created a global observer that automatically sets the `SourceMode` of CadQuery features to `Frozen` when a FreeCAD document is opened.
    * Used a timer mechanism (`QTimer`) and a shared utility module (`cq_utils.py`) to handle FreeCAD's startup/loading sequence correctly and prevent premature script execution before the security check completes.
* **Parameter Linking:**
    * Added an `App::PropertyLink` named `ParameterSource` to the feature.
    * Users can link this property to a FreeCAD Spreadsheet (`Spreadsheet::Sheet`) or a Variable Set (`App::VarSet`).
    * The `execute` method automatically extracts parameters (using Spreadsheet Aliases or VarSet property names) and injects them as variables into the CadQuery script's execution context.
    * Correctly handles FreeCAD's unit system by converting length values (e.g., from Spreadsheets) into unitless floats representing millimeters for CadQuery.
* **Customization:**
    * Implemented a custom icon for the CadQuery feature object in the Tree View.
    * Added custom icons for the "Create CadQuery Feature" and "Edit CadQuery Code" commands in the toolbar and context menu.

## Potential Future Features / Improvements:

* **Interactive Security Prompt:** Instead of automatically freezing, prompt the user on document load with options like "Allow Execution," "Freeze All," or "Review Code."
* **"Trust Document" Mechanism:** Allow users to mark specific FreeCAD documents as trusted, bypassing the automatic freezing for features within those files.
* **Enhanced Error Reporting:** Improve feedback when CadQuery scripts fail. Options include:
    * Displaying errors in a dedicated Task Panel associated with the feature.
    * Attempting to highlight the problematic line number within the linked editor.
* **Task Panel Parameter Editor:** If a feature is linked to a `ParameterSource`, display the available parameters directly in the Task Panel for easier viewing and editing.
* **Relative Paths for Cache:** Enhance `Cache` mode to optionally support referencing script files via paths relative to the FreeCAD document's location, improving project portability.
* **Support for External Libraries:** Develop a mechanism to allow CadQuery scripts within features to import custom Python utility modules or libraries (e.g., from the `Mod` directory or a project subfolder).
* **More Robust URL Fetching:** Add support for authentication (e.g., tokens for private GitHub repos) or handling different HTTP methods/headers for the `URL` mode.
* **Asynchronous Execution:** For complex scripts that take a long time to run, explore executing them in a background thread (using Qt's threading mechanisms carefully) to avoid freezing the FreeCAD interface, possibly adding a progress indicator.