" Vela syntax highlighting.
if exists("b:current_syntax")
  finish
endif

syn keyword velaKeyword fn let mut if else match for in return break continue type import pub test uses with
syn keyword velaContract requires ensures
syn keyword velaStructure struct enum
syn keyword velaBoolean true false
syn keyword velaType Int Byte Bool Str Float Unit Option Result Map
syn keyword velaVariant Some None Ok Err
syn keyword velaBuiltin print len push int byte float assert
syn match velaNumber "\<\d\+\(\.\d\+\)\=\([eE][+-]\=\d\+\)\=\>"
syn match velaEscape contained "\\[nrt0\\\"']"
syn region velaString start=+"+ skip=+\\\\\|\\"+ end=+"+ contains=velaEscape
syn region velaRawString start=+\<r\z(#*)"+ end=+"\z1+ oneline
syn region velaRawString start=+\<r\z(#*)"+ end=+"\z1+ oneline
syn match velaByte "'\(\\.\|[^\\']\)'" contains=velaEscape
syn keyword velaTodo contained TODO FIXME XXX
syn match velaComment "//.*$" contains=velaTodo
syn match velaFunction "\(\<fn\s\+\)\@<=\h\w*"
syn match velaTypeName "\<\u\w*\>"

hi def link velaKeyword Keyword
hi def link velaContract Keyword
hi def link velaStructure Structure
hi def link velaBoolean Boolean
hi def link velaType Type
hi def link velaTypeName Type
hi def link velaVariant Constant
hi def link velaBuiltin Function
hi def link velaFunction Function
hi def link velaNumber Number
hi def link velaString String
hi def link velaRawString String
hi def link velaRawString String
hi def link velaByte Character
hi def link velaEscape SpecialChar
hi def link velaComment Comment
hi def link velaTodo Todo

let b:current_syntax = "vela"
