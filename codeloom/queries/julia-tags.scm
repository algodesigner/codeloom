; Julia tags.scm — tags queries for tree-sitter-julia

(function_definition
  (signature (call_expression
    (identifier) @name))) @definition.function

(struct_definition
  (type_head
    (identifier) @name)) @definition.class

(module_definition
  (identifier) @name) @definition.module
