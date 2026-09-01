from pydantic import BaseModel, Field, model_validator


class WorkflowLimits(BaseModel):
    max_repair_iterations: int = Field(default=2, ge=1, le=3)
    max_review_iterations: int = Field(default=1, ge=0, le=2)


class WorkflowEdge(BaseModel):
    source: str
    target: str


class WorkflowRoute(BaseModel):
    source: str
    router: str
    targets: list[str]


class WorkflowSpec(BaseModel):
    id: str
    version: int = Field(ge=1)
    entrypoint: str
    nodes: list[str]
    edges: list[WorkflowEdge]
    routes: list[WorkflowRoute]
    terminal_nodes: list[str]
    limits: WorkflowLimits = Field(default_factory=WorkflowLimits)

    @model_validator(mode="after")
    def validate_topology(self) -> "WorkflowSpec":
        node_names = set(self.nodes)
        referenced_nodes = {self.entrypoint, *self.terminal_nodes}
        referenced_nodes.update(edge.source for edge in self.edges)
        referenced_nodes.update(edge.target for edge in self.edges)
        referenced_nodes.update(route.source for route in self.routes)
        referenced_nodes.update(target for route in self.routes for target in route.targets)

        unknown_nodes = referenced_nodes - node_names
        if unknown_nodes:
            unknown = ", ".join(sorted(unknown_nodes))
            raise ValueError(f"workflow topology references unknown nodes: {unknown}")
        if len(node_names) != len(self.nodes):
            raise ValueError("workflow nodes must be unique")
        return self

    @property
    def version_id(self) -> str:
        return f"{self.id}@{self.version}"
