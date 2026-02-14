# BrainQuery — A Cypher Subset for TheBrain

BrainQuery is a minimal, Cypher-inspired query language for searching and creating thoughts in TheBrain. It provides a shared formalism between humans and AI agents for expressing graph operations unambiguously.

BrainQuery is **not** a full graph query language. It covers the practical subset needed for everyday brain operations. Advanced graph features (variable-length paths, aggregations, etc.) are deferred to TheBrain v15's native capabilities.

## Quick Examples

```cypher
-- Find a thought by name
MATCH (n {name: "Claude Thoughts"}) RETURN n

-- Find all Person-typed thoughts
MATCH (n:Person) RETURN n

-- Find children of a specific thought
MATCH (n {name: "My Thoughts"})-[:CHILD]->(m) RETURN m

-- Search by substring
MATCH (n) WHERE n.name CONTAINS "MCP" RETURN n

-- Search by prefix
MATCH (n) WHERE n.name STARTS WITH "MCP" RETURN n

-- Fuzzy/similarity search (exact first, then ranked search)
MATCH (n) WHERE n.name =~ "Claude" RETURN n

-- Multi-hop chain (grandchildren)
MATCH (a {name: "Root"})-[:CHILD]->(b)-[:CHILD]->(c) RETURN c

-- Variable-depth traversal (1 to 3 hops)
MATCH (n {name: "Root"})-[:CHILD*1..3]->(d) RETURN d

-- Create a new thought under an existing parent
MATCH (p {name: "Projects"}) CREATE (p)-[:CHILD]->(n {name: "New Project"})

-- Link two existing thoughts
MATCH (a {name: "Alice"}), (b {name: "Bob"}) CREATE (a)-[:JUMP]->(b)
```

## Supported Grammar

### Node Patterns

A node pattern matches or creates a thought. It consists of an optional variable, optional type label, and optional property map.

```
(variable)                          -- any thought
(variable:TypeName)                 -- thought with a specific type
(variable {name: "value"})          -- thought with specific properties
(variable:TypeName {name: "value"}) -- typed thought with properties
```

**Variable**: A lowercase identifier (e.g., `n`, `person`, `src`) used to reference the node elsewhere in the query. Required in all patterns.

**Type label**: Maps to a TheBrain thought type. Case-sensitive, must match an existing type name (e.g., `Person`, `Company`, `Event`).

**Properties**: Key-value pairs in curly braces. Currently only `name` is supported as a property key.

### Relationship Patterns

Relationships connect two node patterns with a direction and type.

```
(a)-[:REL_TYPE]->(b)    -- directed relationship from a to b
```

Supported relationship types and their TheBrain API mappings:

| BrainQuery | TheBrain `relation` | Meaning |
|------------|---------------------|---------|
| `:CHILD`   | 1                   | `b` is a child of `a` |
| `:PARENT`  | 2                   | `b` is a parent of `a` |
| `:JUMP`    | 3                   | Jump link between `a` and `b` |
| `:SIBLING` | 4                   | `b` is a sibling of `a` |

### Variable-Length Paths

Specify how many hops to traverse with `*N` (fixed) or `*N..M` (range):

```cypher
-- Exactly 2 hops (grandchildren)
MATCH (n {name: "Root"})-[:CHILD*2]->(gc) RETURN gc

-- Between 1 and 3 hops deep
MATCH (n {name: "Root"})-[:CHILD*1..3]->(desc) RETURN desc
```

Rules:
- An **explicit upper bound** is always required (max 5).
- `*N` is shorthand for `*N..N`.
- Bare `*` and `*N..` (no upper) are rejected.
- BFS traversal with cycle detection (thoughts are never visited twice).

### Multi-Hop Chains

Chain multiple relationship segments in a single pattern:

```cypher
-- Two-hop chain (find grandchildren via intermediate)
MATCH (a {name: "Root"})-[:CHILD]->(b)-[:CHILD]->(c) RETURN c

-- Intermediate variables are bindable and returnable
MATCH (a {name: "Root"})-[:CHILD]->(b)-[:JUMP]->(c) RETURN b, c

-- Mixed relation types
MATCH (a {name: "Root"})-[:CHILD]->(b)-[:JUMP]->(c)-[:PARENT]->(d) RETURN d
```

### READ Queries (MATCH)

Read queries search for existing thoughts and their connections.

#### Simple node match

```cypher
-- Find by exact name
MATCH (n {name: "Lonnie VanZandt"}) RETURN n

-- Find by type
MATCH (n:Person) RETURN n

-- Find by type and name
MATCH (p:Person {name: "Lonnie VanZandt"}) RETURN p
```

#### Relationship traversal

```cypher
-- Find children of a thought
MATCH (n {name: "My Thoughts"})-[:CHILD]->(m) RETURN m

-- Find parents
MATCH (n {name: "Some Thought"})-[:PARENT]->(p) RETURN p

-- Find jump-linked thoughts
MATCH (n {name: "Concept A"})-[:JUMP]->(j) RETURN j

-- Find siblings
MATCH (n {name: "Task 1"})-[:SIBLING]->(s) RETURN s
```

#### WHERE clause

Adds filters beyond what the node pattern expresses. Five matching modes are available:

```cypher
-- Exact name match (strict, no search fallback)
MATCH (n) WHERE n.name = "Claude Thoughts" RETURN n

-- Substring search (case-insensitive)
MATCH (n) WHERE n.name CONTAINS "MCP" RETURN n

-- Prefix match (case-insensitive)
MATCH (n) WHERE n.name STARTS WITH "MCP" RETURN n

-- Suffix match (case-insensitive)
MATCH (n) WHERE n.name ENDS WITH "Server" RETURN n

-- Similarity search (exact first, then search with ranking)
MATCH (n) WHERE n.name =~ "Claude" RETURN n

-- Combine with type
MATCH (n:Person) WHERE n.name CONTAINS "Van" RETURN n
```

| Operator | Behavior | Use when |
|----------|----------|----------|
| `=` | Strict exact name via `get_thought_by_name`. No fallback. | You know the exact name |
| `CONTAINS` | Search API + substring filter | Partial name recall |
| `STARTS WITH` | Search API + prefix filter | You know how a name begins |
| `ENDS WITH` | Search API + suffix filter | You know how a name ends |
| `=~` | Exact name first, then search with similarity ranking | Fuzzy/approximate lookup |

**Note**: Inline property syntax `{name: "value"}` behaves identically to `WHERE n.name = "value"` — strict exact match with no search fallback. Use `=~` if you want the old fuzzy behavior.

#### RETURN clause

Specifies what to return. Supported forms:

```cypher
RETURN n              -- full thought details
RETURN n.name         -- just the name
RETURN n.id           -- just the thought ID
RETURN n, m           -- multiple variables
RETURN n.name, n.id   -- multiple fields
```

### WRITE Queries (CREATE)

Write queries create new thoughts and links.

#### Create a standalone thought

```cypher
-- Untyped
CREATE (n {name: "New Idea"})

-- Typed
CREATE (n:Concept {name: "New Idea"})
```

#### Create a thought linked to an existing parent

```cypher
-- Create as child of an existing thought
MATCH (p {name: "Projects"}) CREATE (p)-[:CHILD]->(n {name: "New Project"})

-- Create with type
MATCH (p {name: "Projects"}) CREATE (p)-[:CHILD]->(n:Concept {name: "New Idea"})
```

#### Create a link between existing thoughts

```cypher
-- Add a jump link
MATCH (a {name: "Alice"}), (b {name: "Bob"}) CREATE (a)-[:JUMP]->(b)

-- Add a sibling link
MATCH (a {name: "Task 1"}), (b {name: "Task 2"}) CREATE (a)-[:SIBLING]->(b)
```

## Resolution Strategy

When executing a MATCH, the query planner resolves nodes by operator:

| Operator | Resolution path |
|----------|-----------------|
| `=` or `{name: ...}` | `get_thought_by_name()` only. Strict. |
| `CONTAINS` | `search_thoughts()` → post-filter by substring |
| `STARTS WITH` | `search_thoughts()` → post-filter by prefix |
| `ENDS WITH` | `search_thoughts()` → post-filter by suffix |
| `=~` | `get_thought_by_name()` first, then `search_thoughts()` fallback with similarity ranking |
| Type label only | `get_types()` → return the type thought itself |

After candidate resolution, **type filtering** is applied lazily — only if candidates exist and a type label is specified.

**Critical rule**: Type thoughts are uber-nodes in personal brains (e.g., Person may have 1,000+ children). The planner never traverses down from a Type to find matches. Type is always a deferred filter, not a starting point. The only exception is when the user explicitly requests all thoughts of a type (`MATCH (n:Person) RETURN n`).

## What's NOT Supported

The following Cypher features are explicitly out of scope. BrainQuery will return a helpful error if you attempt them, suggesting the supported alternative.

| Feature | Why excluded | Alternative |
|---------|-------------|-------------|
| `DELETE` / `DETACH DELETE` | Destructive — use dedicated `delete_thought` tool | `delete_thought` tool |
| `SET` for property updates | Use dedicated tool | `update_thought` tool |
| `MERGE` (upsert) | Complex semantics, risk of silent duplicates | MATCH first, then CREATE if not found |
| Aggregations (`COUNT`, `COLLECT`) | Not a reporting tool | Use `get_brain_stats` for counts |
| `OPTIONAL MATCH` | Adds null-handling complexity | Run two separate queries |
| `UNION` | Use separate queries | Run queries independently |
| Path variables `p = (a)-[*]->(b)` | No multi-hop support | Step-by-step traversal |
| `WHERE` with `AND`/`OR` | Keep filtering simple for v1 | Multiple queries |
| Numeric/boolean properties | Only `name` is queryable via TheBrain API | Use notes for rich metadata |

## Formal Grammar (EBNF)

```ebnf
query           = match_query | create_query | match_create_query ;

match_query     = "MATCH" , match_pattern , { "," , match_pattern } ,
                  [ where_clause ] , return_clause ;

create_query    = "CREATE" , create_pattern , { "," , create_pattern } ;

match_create_query = "MATCH" , match_pattern , { "," , match_pattern } ,
                     "CREATE" , create_pattern , { "," , create_pattern } ;

match_pattern   = node_pattern , { rel_pattern , node_pattern } ;

create_pattern  = node_pattern , { rel_pattern , node_pattern } ;

node_pattern    = "(" , variable , [ ":" , type_label ] ,
                  [ "{" , property_map , "}" ] , ")" ;

rel_pattern     = "-[" , ":" , rel_type , [ hop_spec ] , "]->" ;
hop_spec        = "*" , int , ".." , int
                | "*" , int ;

variable        = identifier ;
type_label      = identifier ;
identifier      = letter , { letter | digit | "_" } ;

property_map    = property , { "," , property } ;
property        = "name" , ":" , string_literal ;

string_literal  = '"' , { any_char - '"' } , '"' ;

where_clause    = "WHERE" , where_expr ;
where_expr      = variable , "." , "name" , where_op , string_literal ;
where_op        = "=" | "CONTAINS" | "STARTS" , "WITH"
                | "ENDS" , "WITH" | "=~" ;

return_clause   = "RETURN" , return_item , { "," , return_item } ;
return_item     = variable , [ "." , field_name ] ;
field_name      = "name" | "id" ;

rel_type        = "CHILD" | "PARENT" | "JUMP" | "SIBLING" ;
```

## TheBrain Mapping Reference

| BrainQuery Concept | TheBrain Equivalent |
|--------------------|---------------------|
| Node label (`:Person`) | Thought type (`typeId`) |
| Node property `name` | Thought `name` field |
| `:CHILD` relationship | `relation: 1` in link/graph API |
| `:PARENT` relationship | `relation: 2` |
| `:JUMP` relationship | `relation: 3` |
| `:SIBLING` relationship | `relation: 4` |
| `MATCH` | `get_thought_by_name`, `search_thoughts`, `get_thought_graph` |
| `CREATE` node | `create_thought` API |
| `CREATE` relationship | `create_link` API |
| `RETURN` | Response formatting (thought ID, name, type) |
