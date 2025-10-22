# (c) 2014-2025 CadQuery Developers

"""
CadQuery GUI init module for FreeCAD
This adds a workbench with a scripting editor to FreeCAD's GUI.
"""

import Part, FreeCAD, FreeCADGui
from CQGui.Command import (CadQueryHelp,
                           CadQueryClearOutput,
                           CadQueryStableInstall,
                           CadQueryUnstableInstall,
                           CadQueryCreateFeature,
                           EditCQCodeCmd,
                           Build123DInstall)


class CadQueryWorkbench (Workbench):
    """CadQuery workbench for FreeCAD"""
      
    MenuText = "CadQuery"
    ToolTip = "CadQuery workbench"


    def Initialize(self):
        self.appendMenu('CadQuery', ['CadQueryClearOutput'])
        self.appendMenu(['CadQuery', 'Install'], ["CadQueryStableInstall",
                                                  "CadQueryUnstableInstall",
                                                  "Build123DInstall"])
        self.appendMenu('CadQuery', ['CadQueryHelp'])
        # 1. Define a list for your new parametric tools
        self.parametric_tools = [
            "CadQueryCreateFeature",
            "EditCQCode"]


        # 2. Register the new command with FreeCAD's GUI system
        #FreeCADGui.addCommand("CreateCQFeature", CadQueryCreateFeature())

        # 3. Add a new toolbar for these tools
        self.appendToolbar("CadQuery Parametric", self.parametric_tools)

        # 4. Add the command to the main menu as well
        self.appendMenu("CadQuery", self.parametric_tools)

    def Activated(self):
        pass


    def Deactivated(self):
        pass



FreeCADGui.addCommand('CadQueryStableInstall', CadQueryStableInstall())
FreeCADGui.addCommand('CadQueryUnstableInstall', CadQueryUnstableInstall())
FreeCADGui.addCommand('CadQueryCreateFeature', CadQueryCreateFeature())
FreeCADGui.addCommand('Build123DInstall', Build123DInstall())
FreeCADGui.addCommand('CadQueryClearOutput', CadQueryClearOutput())
FreeCADGui.addCommand('CadQueryHelp', CadQueryHelp())
FreeCADGui.addCommand('EditCQCode', EditCQCodeCmd())
FreeCADGui.addWorkbench(CadQueryWorkbench())
