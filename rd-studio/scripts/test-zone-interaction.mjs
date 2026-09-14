import assert from 'node:assert/strict';
import {snappedMove} from '../lib/zone-interaction.ts';
assert.equal(snappedMove([12,5,2],[10,3],[10,3]),null,'selection alone must not submit an edit');
assert.equal(snappedMove([12,5,2],[10,3],[10.1,2.9]),null,'sub-grid movement must not dirty the design');
assert.deepEqual(snappedMove([12,5,2],[10,3],[10.26,3]),[12.25,5,2]);
assert.deepEqual(snappedMove([12.25,5,2],[10,3],[10.26,3]),[12.5,5,2]);
assert.equal(snappedMove([12,5,2],[10,3],[9.75,3],[.25,0]),null,'dragging back to origin must not commit');
console.log('No-op selection, snapped consecutive moves, and elevation preservation passed.');
