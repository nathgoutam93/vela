Write the module `shapes.vl`:

    pub type Shape = enum {
        Circle(Float)                 // radius
        Rect(Float, Float)            // width, height
        Triangle(Float, Float, Float) // the three sides
    }

    pub fn area(s: Shape) -> Option[Float]
    pub fn perimeter(s: Shape) -> Option[Float]
    pub fn largest(shapes: [Shape]) -> Option[Int]

A shape is valid when all its sizes are greater than 0 and, for a
triangle, each side is shorter than the sum of the other two. `area` and
`perimeter` return `None` for a shape that is not valid. A triangle's
area comes from Heron's formula; use 3.141592653589793 for pi.

`largest` returns the index of the valid shape with the largest area, the
first one if several have it, and `None` if no shape is valid.
