# Follow-up native preflight audit

After applying PR21 interface evidence, inspect current PR20 rather than copying old local patches. Additional confirmed code gaps: empty/duplicate feature plans could reach native creation; envelope comparisons could truncate with zip on malformed expected lengths; driving dimension units allowed count/ratio/boolean through the shared native property converter.

New pure validation runs before owned SW spawn and again before document creation. It requires unique named features, predecessor order, explicit sketch geometry/planes, valid line/circle/arc coordinates, consumed sketch dependencies, length/angle driving dimensions, exact positive finite envelope dimensions and body counts. Existing advanced mapping validation remains intact. No session gates relaxed; p248 generator untouched.

Six focused offline regressions passed. Windows and full regression not run. Formal native acceptance is still blocked by the test host's inability to prove owned COM identity; warm gate bypass is not a solution. Generic feature-data/property bindings still need Windows review. Use the current source archive for retest; earlier ZIP snapshots do not contain later audit fixes.
