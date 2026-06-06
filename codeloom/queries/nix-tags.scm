; Nix tags.scm — tags queries for tree-sitter-nix

(apply_expression
  function: [
    (variable_expression
      (identifier) @name)
    (select_expression
      attrpath: (attrpath
        attr: (identifier) @name .))
  ]) @reference.call
