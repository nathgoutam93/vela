Write the module `stack.vl`, a stack that holds values of any one type:

    pub type Stack[T] = struct { ... }      // what is inside is up to you

    pub fn new[T]() -> Stack[T]
    pub fn add[T](s: mut Stack[T], x: T)
    pub fn pop[T](s: mut Stack[T]) -> Option[T]     // None when empty
    pub fn peek[T](s: Stack[T]) -> Option[T]        // the top, without removing it
    pub fn size[T](s: Stack[T]) -> Int

(A module cannot define a function called `push`: it is a built-in.)

It is used like this:

    let mut s: stack.Stack[Str] = stack.new()
    stack.add(mut s, "a")
