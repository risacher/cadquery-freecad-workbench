import cadquery as cq

# Create the model that we want to display
box = cq.Workplane().box(10, 10, 5)

# You can output a message to FreeCAD's Report view
print("I want to display something in the Report view")

# You can set a custom name for for the part object in FreeCAD's model tree
box.val().label = "My_Box"



# Display the object in a new document tab
#show_object(box)

result = box