; Zig tags.scm — tags queries for tree-sitter-zig

(function_declaration
  name: (identifier) @name) @definition.function

(variable_declaration
  (identifier) @name
  "="
  (struct_declaration)) @definition.class

(variable_declaration
  (identifier) @name
  "="
  (enum_declaration)) @definition.enum
