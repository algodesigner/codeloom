; Perl tags.scm — tags queries for tree-sitter-perl

(subroutine_declaration_statement
  name: (bareword) @name) @definition.function

(method_declaration_statement
  name: (bareword) @name) @definition.method

(package_statement
  (package) @name) @definition.class

(class_statement
  (package) @name) @definition.class
