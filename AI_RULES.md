# AI Development Rules

## Architecture

- Preserve the current Clean Architecture dependency direction.
- Domain must not depend on application, infrastructure, presentation, or frontend.
- Application use cases coordinate workflows; they must not become collections of unrelated private helpers.
- Infrastructure implements application ports and must not own domain decisions.
- Presentation and frontend must not duplicate domain rules.
- Keep responsibilities highly cohesive and dependencies explicit.

## Abstraction Rules

- Do not introduce services, factories, mappers, policies, strategies, wrappers, adapters, repositories, DTOs, or helper classes without a concrete requirement.
- Do not create an abstraction only because it may be useful in the future.
- Do not extract a single-use helper merely to shorten a method.
- Prefer existing concepts over introducing parallel concepts.
- A new abstraction must remove real duplication, isolate a real dependency, or represent a real domain concept.

## Duplication and Source of Truth

- Before adding a field, variable, enum, model, DTO, method, or class, search for an existing concept with the same meaning.
- Do not represent the same state using multiple fields.
- Do not duplicate validation, mapping, selection, filtering, or conversion logic.
- Domain state must have one clear source of truth.
- Delete obsolete implementations after replacement.
- Do not retain compatibility code unless explicitly required.

## Use Cases

- Use cases should expose the application operation clearly.
- Do not add private helper methods that hide domain or infrastructure responsibilities.
- Do not place object construction, data mapping, domain calculations, or repository-specific logic inside use cases unless it is directly part of orchestration.
- Repeated or complex business decisions belong in an appropriate domain object or domain rule.
- Infrastructure-specific conversion belongs in infrastructure.

## Naming

- Use names that match existing domain terminology.
- Do not create aliases for existing concepts.
- Avoid vague names such as manager, handler, processor, helper, util, or service unless the responsibility is precise.
- Avoid unnecessary abbreviations.
- Persisted string enums should use StrEnum where appropriate.

## Change Control

- Modify only files required by the approved design.
- Do not modify unrelated code.
- Do not silently expand the scope.
- Report additional required changes before implementing them.
- Do not leave deprecated code, unused imports, obsolete TODOs, compatibility branches, or duplicate implementations.
- Return complete replacement code only for files that require modification.
- Explicitly list files to modify, add, and delete.

## Self-Review

Before returning code, verify:

- No unnecessary helper was introduced.
- No duplicate state or variable was introduced.
- No responsibility was duplicated.
- No additional source of truth was created.
- No unapproved abstraction was introduced.
- No unrelated file was modified.
- No obsolete implementation remains.
- Dependency direction is preserved.
- All callers, implementations, dependency wiring, tests, API schemas, and frontend consumers remain consistent.