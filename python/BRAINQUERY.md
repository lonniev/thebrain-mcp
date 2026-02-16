# BrainQuery — A Cypher Subset for TheBrain

BrainQuery is a minimal, Cypher-inspired query language for searching and creating thoughts in TheBrain. It provides a shared formalism between humans and AI agents for expressing graph operations unambiguously.

BrainQuery is **not** a full graph query language. It covers the practical subset needed for everyday brain operations. Advanced graph features (aggregations, etc.) are deferred to TheBrain v15's native capabilities.

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

-- Wildcard: traverse any relation type (children, jumps, siblings)
MATCH (n {name: "Root"})-->(m) RETURN m

-- Union: traverse multiple relation types
MATCH (n {name: "Root"})-[:CHILD|JUMP]->(m) RETURN m

-- Wildcard variable-length (explore neighborhood)
MATCH (n {name: "Root"})-[*1..2]->(m) RETURN m

-- Find children with labels (IS NOT NULL)
MATCH (a {name: "Root"})-[:CHILD]->(c) WHERE c.label IS NOT NULL RETURN c

-- Find untyped descendants (IS NULL)
MATCH (a {name: "Root"})-[:CHILD*1..2]->(c) WHERE c.typeId IS NULL RETURN c

-- Update a thought's label
MATCH (p {name: "Projects"}) SET p.label = "Active Projects" RETURN p

-- Rename a thought
MATCH (p {name: "Old Name"}) SET p.name = "New Name" RETURN p

-- Set a type on a thought
MATCH (p {name: "Untyped"}) SET p:Person RETURN p

-- Clear a property
MATCH (p {name: "Projects"}) SET p.label = NULL RETURN p

-- Upsert: create if not exists, match if exists
MERGE (p {name: "Meeting Notes"}) RETURN p

-- MERGE with conditional SET
MERGE (p {name: "Test"})
ON CREATE SET p.label = "New"
ON MATCH SET p.label = "Existing"
RETURN p

-- MERGE a relationship (idempotent link)
MATCH (a {name: "Alice"}), (b {name: "Bob"}) MERGE (a)-[:JUMP]->(b)

-- Delete a thought (preview by default, confirm=true to execute)
MATCH (n {name: "Old Note"}) DELETE n

-- Delete a relationship (keep the thoughts)
MATCH (a {name: "Alice"})-[r:JUMP]->(b {name: "Bob"}) DELETE r

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
(a)-[:REL_TYPE]->(b)         -- single relation type
(a)-->(b)                    -- wildcard: any relation type
(a)-[:CHILD|JUMP]->(b)       -- union: multiple relation types
(a)-[r:CHILD]->(b)           -- named relationship variable
(a)-[r]->(b)                 -- named wildcard variable
```

Supported relationship types and their TheBrain API mappings:

| BrainQuery | TheBrain `relation` | Meaning |
|------------|---------------------|---------|
| `:CHILD`   | 1                   | `b` is a child of `a` |
| `:PARENT`  | 2                   | `b` is a parent of `a` |
| `:JUMP`    | 3                   | Jump link between `a` and `b` |
| `:SIBLING` | 4                   | `b` is a sibling of `a` |

#### Wildcard Relations

The `-->` shorthand (or `-[]->`) traverses all forward relation types: children, jumps, and siblings. Parents are excluded to prevent upward explosion.

```cypher
-- Find all directly connected thoughts (children + jumps + siblings)
MATCH (n {name: "Root"})-->(m) RETURN m

-- Same with empty brackets
MATCH (n {name: "Root"})-[]->(m) RETURN m

-- Wildcard with variable-length path
MATCH (n {name: "Root"})-[*1..2]->(m) RETURN m

-- Named wildcard variable
MATCH (n {name: "Root"})-[r]->(m) RETURN m
```

#### Union Relations

Combine multiple relation types with `|` to traverse several types at once:

```cypher
-- Children and jumps (but not siblings)
MATCH (n {name: "Root"})-[:CHILD|JUMP]->(m) RETURN m

-- Union with variable-length path
MATCH (n {name: "Root"})-[:CHILD|JUMP*1..3]->(m) RETURN m

-- Named union variable
MATCH (n {name: "Root"})-[r:CHILD|JUMP]->(m) RETURN m
```

**Rules:**
- Wildcard and union are **read-only** — `CREATE` and `MERGE` require exactly one explicit relation type.
- `DELETE` of a relationship variable also requires exactly one type (e.g., `-[r:JUMP]->`).
- Wildcards exclude `:PARENT` to prevent traversal from exploding upward.
- Union types are case-insensitive.

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

#### Compound WHERE Conditions

Combine multiple conditions with `AND`, `OR`, `NOT`, and `XOR`. Standard Cypher precedence applies: `NOT` > `AND` > `XOR` > `OR`. Use parentheses to override.

```cypher
-- AND: both conditions must match
MATCH (n) WHERE n.name CONTAINS "MCP" AND n.name ENDS WITH "Server" RETURN n

-- OR: either condition matches (same variable only)
MATCH (n) WHERE n.name = "Alice" OR n.name = "Bob" RETURN n

-- NOT: exclude matches (prefix unary)
MATCH (a {name: "Root"})-[:CHILD]->(p)
WHERE NOT p.name =~ "Kelsey"
RETURN p

-- NOT with AND: positive clause drives search, NOT filters
MATCH (n) WHERE n.name =~ "Lonnie" AND NOT n.name CONTAINS "Jr" RETURN n

-- NOT with parenthesized group
MATCH (a {name: "Root"})-[:CHILD]->(p)
WHERE NOT (p.name =~ "Kelsey" OR p.name =~ "Meagan")
RETURN p

-- XOR: exactly one condition true (symmetric difference)
MATCH (n) WHERE n.name CONTAINS "Kelsey" XOR n.name CONTAINS "Meagan" RETURN n

-- Parentheses override precedence
MATCH (n) WHERE (n.name CONTAINS "Server" OR n.name CONTAINS "Client") AND n.name STARTS WITH "MCP" RETURN n

-- AND across different variables in a chain
MATCH (a {name: "Root"})-[:CHILD]->(b)
WHERE a.name = "Root" AND b.name CONTAINS "Project"
RETURN b
```

| Operator | Precedence | Meaning |
|----------|------------|---------|
| `NOT` | 1 (highest) | Negation (prefix unary) |
| `AND` | 2 | Both conditions must be true |
| `XOR` | 3 | Exactly one condition true |
| `OR` | 4 (lowest) | At least one condition true |

**Rules:**
- `AND` across different variables is allowed — each condition is routed to its respective variable.
- `OR` and `XOR` across different variables are **not** supported (use separate queries instead).
- `NOT` cannot be the sole constraint on a directly-resolved node — it needs a positive constraint or chain-provided candidate set to filter against.
- All logical keywords (`AND`, `OR`, `NOT`, `XOR`) are case-insensitive.

#### Property Existence Checks (IS NULL / IS NOT NULL)

Check whether a thought has a value for a given property:

```cypher
-- Find children with labels (subtitle)
MATCH (a {name: "Lonnie VanZandt"})-[:CHILD]->(c)
WHERE c.label IS NOT NULL
RETURN c

-- Find untyped children
MATCH (a {name: "Claude Thoughts"})-[:CHILD*1..2]->(c)
WHERE c.typeId IS NULL
RETURN c

-- Combine with name conditions
MATCH (a {name: "Lonnie VanZandt"})-[:CHILD]->(c:Person)
WHERE c.label IS NOT NULL AND c.name =~ "Kelsey"
RETURN c
```

Supported properties:

| Property | Description | When null |
|----------|-------------|-----------|
| `label` | Subtitle/description text | Most thoughts |
| `typeId` | ID of the thought's type | Untyped thoughts |
| `foregroundColor` | Text color hex | Uses default |
| `backgroundColor` | Background color hex | Uses default |
| `kind` | Thought kind (1=Normal, etc.) | Never null |
| `name` | Thought name | Never null |
| `id` | Thought ID | Never null |

**Rules:**
- IS NULL / IS NOT NULL are **post-filters** — they cannot drive a search on their own.
- They must be combined with a name condition (via AND) or used on a traversal target where the chain provides candidates.
- Property names are case-insensitive (`typeId`, `typeid`, and `TYPEID` all work).
- `name IS NULL` always returns empty; `name IS NOT NULL` always returns all candidates.

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

### UPDATE Queries (SET)

SET modifies properties of matched thoughts. The SET clause goes between WHERE and RETURN.

#### Set a property

```cypher
-- Set label
MATCH (p {name: "Projects"}) SET p.label = "Active Projects" RETURN p

-- Rename a thought
MATCH (p {name: "Old Name"}) SET p.name = "New Name" RETURN p

-- Set multiple properties
MATCH (p {name: "X"}) SET p.label = "Sub", p.foregroundColor = "#0000ff" RETURN p
```

#### Clear a property

```cypher
MATCH (p {name: "X"}) SET p.label = NULL RETURN p
```

#### Set type

```cypher
MATCH (p {name: "Untyped Thought"}) SET p:Person RETURN p
```

#### SET in a chain context

```cypher
MATCH (a {name: "Root"})-[:CHILD]->(p:Person)
WHERE p.name =~ "Kelsey"
SET p.label = "Daughter"
RETURN p
```

Settable properties:

| Property | Description | Notes |
|----------|-------------|-------|
| `name` | Thought name | Renames the thought |
| `label` | Subtitle text | Set NULL to clear |
| `foregroundColor` | Text color | Hex format e.g. "#ff0000" |
| `backgroundColor` | Background color | Hex format e.g. "#0000ff" |

**Safety rules:**
- SET has a batch limit of 10 thoughts. If MATCH resolves more, an error is returned.
- `id`, `typeId`, and `kind` cannot be SET via property assignment. Use `SET p:TypeName` for type changes.

### UPSERT Queries (MERGE)

MERGE provides "match or create" semantics for idempotent operations. If a thought matching the pattern exists, it's returned; if not, it's created.

#### Basic MERGE

```cypher
-- Find or create
MERGE (p {name: "Meeting Notes"}) RETURN p

-- Typed MERGE
MERGE (p:Person {name: "New Contact"}) RETURN p
```

#### Conditional SET (ON CREATE / ON MATCH)

```cypher
MERGE (p {name: "Weekly Review"})
ON CREATE SET p.label = "Created by agent"
ON MATCH SET p.label = "Updated by agent"
RETURN p
```

#### MERGE relationship (idempotent link)

```cypher
-- Create link only if it doesn't exist
MATCH (a {name: "Alice"}), (b {name: "Bob"})
MERGE (a)-[:JUMP]->(b)

-- MERGE child with conditional SET
MATCH (parent {name: "Projects"})
MERGE (parent)-[:CHILD]->(c {name: "new-project"})
ON CREATE SET c.label = "Created via BrainQuery"
RETURN c
```

**Rules:**
- MERGE requires a `{name: "..."}` constraint. `MERGE (p:Person)` without a name is rejected.
- MERGE uses strict exact match (`get_thought_by_name`).
- If multiple thoughts match, the first is used and a warning is returned.
- ON CREATE SET is applied only when creating a new thought.
- ON MATCH SET is applied only when matching an existing thought.

### DELETE Queries (MATCH + DELETE)

DELETE removes matched thoughts or relationships. It always requires a MATCH clause first.

**Two-phase execution**: DELETE uses a dry-run preview by default. Call with `confirm=true` to execute.

#### Delete a thought

```cypher
-- Preview what would be deleted (dry-run)
MATCH (n {name: "Old Note"}) DELETE n

-- Actually delete (with confirm=true)
MATCH (n {name: "Old Note"}) DELETE n
```

#### Delete with WHERE filter

```cypher
-- Delete specific children
MATCH (a {name: "Root"})-[:CHILD]->(b)
WHERE b.name = "Obsolete"
DELETE b
```

#### Delete a relationship (keep the thoughts)

```cypher
-- Remove a jump link between two thoughts
MATCH (a {name: "Alice"})-[r:JUMP]->(b {name: "Bob"}) DELETE r
```

#### DETACH DELETE

```cypher
-- DETACH DELETE is accepted for Cypher compatibility (same behavior in TheBrain)
MATCH (n {name: "Old"}) DETACH DELETE n
```

#### Delete multiple targets

```cypher
MATCH (a {name: "A"}), (b {name: "B"}) DELETE a, b
```

**Rules:**
- DELETE always requires MATCH (standalone `DELETE (n)` is rejected).
- SET and DELETE cannot be combined in the same query.
- A batch limit of 5 thoughts applies. If MATCH resolves more, an error is returned.
- Relationship variables (`-[r:TYPE]->`) allow deleting links without deleting thoughts.
- DETACH DELETE is accepted for Cypher compatibility but behaves identically to DELETE (TheBrain handles orphan cleanup).
- The `confirm` parameter must be set to `true` to actually execute the deletion. Without it, a preview of what would be deleted is returned.

## Best Practices: Query Scoping

Generic names like "In-Progress", "Done", "TASKS", and "Proposed" appear in multiple sub-graphs when a Brain has several projects following the same structural pattern (e.g., Kanban boards, date hierarchies). BQL's search index returns whichever match it finds first — often the wrong one.

### Always scope from a unique name

Anchor your query at a thought with a globally unique name and traverse down to the target. This is the BQL equivalent of schema-qualifying table names in SQL.

```cypher
-- BAD: "In-Progress" exists under every project's TASKS board
MATCH (p {name: "In-Progress"})-[:CHILD]->(t) RETURN t

-- GOOD: scope from the unique project name
MATCH (proj {name: "thebrain-mcp"})-[:CHILD]->(tasks {name: "TASKS"})
      -[:CHILD]->(ip {name: "In-Progress"})-[:CHILD]->(t)
RETURN t
```

### Use wildcard hops to bridge structural layers

When a path crosses several intermediate layers (Project → TASKS → Column → Task), use `*N..M` to skip layers you don't need to name individually.

```cypher
-- Bridge 2-3 layers without naming each intermediate
MATCH (proj {name: "thebrain-mcp"})-[:CHILD*2..3]->(ip)
WHERE ip.name = "In-Progress"
RETURN ip

-- Explore a subtree without knowing exact depth
MATCH (root {name: "Claude Thoughts"})-[:CHILD*1..3]->(d)
WHERE d.name CONTAINS "MCP"
RETURN d
```

### Filter at the leaf, not the root

Anchor on the unique ancestor, fan out with wildcards, and use WHERE to filter the results. This avoids ambiguous root matches.

```cypher
-- Find all tasks tagged "urgent" under a specific project
MATCH (proj {name: "thebrain-mcp"})-[:CHILD*1..4]->(t)
WHERE t.name CONTAINS "urgent"
RETURN t
```

---

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
| Aggregations (`COUNT`, `COLLECT`) | Not a reporting tool | Use `get_brain_stats` for counts |
| `OPTIONAL MATCH` | Adds null-handling complexity | Run two separate queries |
| `UNION` | Use separate queries | Run queries independently |
| Path variables `p = (a)-[*]->(b)` | Path binding not supported | Use variable-length paths or chains |
| `OR` across different variables | Cross-variable OR has ambiguous semantics | Use separate queries |
| Property value comparisons (except `name`) | Only `name` supports value operators (`=`, `CONTAINS`, etc.) | Use `IS NULL`/`IS NOT NULL` for existence checks on other properties |
| Standalone `DELETE` without `MATCH` | Always requires a MATCH clause | Use `MATCH ... DELETE` |

## Formal Grammar (EBNF)

```ebnf
query           = match_query | create_query | match_create_query
                | merge_query | match_merge_query | match_delete_query ;

match_query     = "MATCH" , match_pattern , { "," , match_pattern } ,
                  [ where_clause ] , [ set_clause ] , return_clause ;

create_query    = "CREATE" , create_pattern , { "," , create_pattern } ;

match_create_query = "MATCH" , match_pattern , { "," , match_pattern } ,
                     "CREATE" , create_pattern , { "," , create_pattern } ;

merge_query     = "MERGE" , merge_pattern , { "," , merge_pattern } ,
                  [ on_create_clause ] , [ on_match_clause ] ,
                  [ return_clause ] ;

match_merge_query = "MATCH" , match_pattern , { "," , match_pattern } ,
                    "MERGE" , merge_pattern , { "," , merge_pattern } ,
                    [ on_create_clause ] , [ on_match_clause ] ,
                    [ return_clause ] ;

match_delete_query = "MATCH" , match_pattern , { "," , match_pattern } ,
                     [ where_clause ] , delete_clause ;

merge_pattern   = node_pattern , { rel_pattern , node_pattern } ;

on_create_clause = "ON" , "CREATE" , "SET" , set_item , { "," , set_item } ;
on_match_clause  = "ON" , "MATCH" , "SET" , set_item , { "," , set_item } ;

match_pattern   = node_pattern , { rel_pattern , node_pattern } ;

create_pattern  = node_pattern , { rel_pattern , node_pattern } ;

node_pattern    = "(" , variable , [ ":" , type_label ] ,
                  [ "{" , property_map , "}" ] , ")" ;

rel_pattern     = "-->"
                | "-[" , "]->"
                | "-[" , [ variable , ":" ] , relation_types , [ hop_spec ] , "]->"
                | "-[" , variable , [ hop_spec ] , "]->"
                | "-[" , hop_spec , "]->" ;
relation_types  = rel_type , { "|" , rel_type } ;
hop_spec        = "*" , int , ".." , int
                | "*" , int ;

variable        = identifier ;
type_label      = identifier ;
identifier      = letter , { letter | digit | "_" } ;

property_map    = property , { "," , property } ;
property        = "name" , ":" , string_literal ;

string_literal  = '"' , { any_char - '"' } , '"' ;

where_clause    = "WHERE" , or_expr ;
or_expr         = and_expr , { "OR" , and_expr } ;
and_expr        = where_atom , { "AND" , where_atom } ;
where_atom      = "(" , or_expr , ")"
                | variable , "." , property_name , "IS" , "NOT" , "NULL"
                | variable , "." , property_name , "IS" , "NULL"
                | variable , "." , "name" , where_op , string_literal ;
where_op        = "=" | "CONTAINS" | "STARTS" , "WITH"
                | "ENDS" , "WITH" | "=~" ;
property_name   = "name" | "id" | "label" | "typeId"
                | "foregroundColor" | "backgroundColor" | "kind" ;

set_clause      = "SET" , set_item , { "," , set_item } ;
set_item        = variable , "." , settable_prop , "=" , ( string_literal | "NULL" )
                | variable , ":" , type_label ;
settable_prop   = "name" | "label" | "foregroundColor" | "backgroundColor" ;

delete_clause   = [ "DETACH" ] , "DELETE" , variable , { "," , variable } ;

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
| `DELETE` node | `delete_thought` API |
| `DELETE` relationship | `delete_link` API |
| `RETURN` | Response formatting (thought ID, name, type) |
