import libcst

from swesmith.bug_gen.procedural.python.base import PythonProceduralModifier
from swesmith.constants import CodeProperty


class EmptyBodyModifier(PythonProceduralModifier):
    """Replace function/class body with empty body (just pass)."""

    explanation: str = "The function/class body has been replaced with a pass statement."
    name: str = "func_pm_empty_body"
    conditions: list = [CodeProperty.IS_FUNCTION]

    class Transformer(PythonProceduralModifier.Transformer):
        def __init__(self, parent_modifier):
            super().__init__(parent_modifier)
            self.modified = False

        def leave_FunctionDef(self, original_node, updated_node):
            if not self.flip():
                return updated_node

            # Create the empty body with just a pass statement
            empty_body = libcst.IndentedBlock(
                body=[
                    libcst.SimpleStatementLine(
                        body=[libcst.Pass()],
                    )
                ]
            )
            self.modified = True
            return updated_node.with_changes(body=empty_body)

        def leave_ClassDef(self, original_node, updated_node):
            if not self.flip():
                return updated_node

            # Create the empty body with just a pass statement
            empty_body = libcst.IndentedBlock(
                body=[
                    libcst.SimpleStatementLine(
                        body=[libcst.Pass()],
                    )
                ]
            )
            self.modified = True
            return updated_node.with_changes(body=empty_body)
