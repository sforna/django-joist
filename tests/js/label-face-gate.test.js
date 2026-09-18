import test from 'node:test';
import assert from 'node:assert/strict';

import { labelFaceGate } from '../../src/django_joist/static/joist/js/label-face-gate.js';

// Mermaid sizes every label box to the text it measured and leaves no slack, so
// a box measured in the fallback face clips the last character once the real
// face swaps in: on a host whose fallback is narrower, every label overflowed.
// The policy is three-part, and the third part is what makes the second safe:
// wait for the face, give up rather than hold the canvas blank, and redraw once
// if the face arrives after we gave up.

/** A FontFaceSet stand-in: records what was asked for. */
function fakeFonts({ resolve = () => [{ family: 'IBM Plex Mono' }], after = 0 } = {}) {
  const asked = [];
  return {
    asked,
    load(face) {
      asked.push(face);
      return new Promise((done, fail) => {
        setTimeout(() => {
          const value = resolve(face);
          if (value instanceof Error) fail(value);
          else done(value);
        }, after);
      });
    },
  };
}

const tick = (ms = 15) => new Promise((done) => setTimeout(done, ms));

test('it resolves true once the faces are loaded', async () => {
  const fonts = fakeFonts();
  const gate = labelFaceGate({ fonts, faces: ['12px "IBM Plex Mono"'], timeoutMs: 1000 });

  assert.equal(await gate.settled(), true);
  assert.deepEqual(fonts.asked, ['12px "IBM Plex Mono"']);
});

test('it gives up after the timeout instead of holding the canvas blank', async () => {
  const fonts = fakeFonts({ after: 10_000 });
  const gate = labelFaceGate({ fonts, faces: ['12px "IBM Plex Mono"'], timeoutMs: 5 });

  assert.equal(await gate.settled(), false);
});

test('the faces are requested once, however many renders ask', async () => {
  const fonts = fakeFonts();
  const gate = labelFaceGate({ fonts, faces: ['a', 'b'], timeoutMs: 1000 });

  const [first, second] = await Promise.all([gate.settled(), gate.settled()]);
  assert.equal(first, true);
  assert.equal(second, true);
  assert.deepEqual(fonts.asked, ['a', 'b']);
});

test('a load that fails is settled, not a reason to wait forever', async () => {
  // The face will never arrive: measuring in the fallback now is the honest
  // outcome, and the timeout must not be the only way out.
  const fonts = fakeFonts({ resolve: () => new Error('no such face') });
  const gate = labelFaceGate({ fonts, faces: ['nope'], timeoutMs: 10_000 });

  assert.equal(await gate.settled(), true);
});

test('a late face redraws once, and the gate then reports settled', async () => {
  const fonts = fakeFonts({ after: 25 });
  const gate = labelFaceGate({ fonts, faces: ['12px "IBM Plex Mono"'], timeoutMs: 5 });

  let redraws = 0;
  assert.equal(await gate.settled(), false); // gave up
  gate.whenLate(() => {
    redraws += 1;
  });

  await tick(60);
  assert.equal(redraws, 1);
  assert.equal(await gate.settled(), true);
});

test('several late registrations still redraw once', async () => {
  const fonts = fakeFonts({ after: 25 });
  const gate = labelFaceGate({ fonts, faces: ['face'], timeoutMs: 5 });

  let redraws = 0;
  await gate.settled();
  gate.whenLate(() => {
    redraws += 1;
  });
  gate.whenLate(() => {
    redraws += 1;
  });

  await tick(60);
  assert.equal(redraws, 1);
});

test('a face that never arrives does not redraw into a broken measurement', async () => {
  // fonts.load() resolves with the faces that matched, so an unmatched family
  // gives []; counting that as an arrival would redraw for nothing.
  const fonts = fakeFonts({ resolve: () => [] });
  const gate = labelFaceGate({ fonts, faces: ['missing'], timeoutMs: 1000 });

  let redraws = 0;
  await gate.settled();
  gate.whenLate(() => {
    redraws += 1;
  });

  await tick(40);
  assert.equal(redraws, 0);
});

test('whenLate on its own starts the load rather than dereferencing null', async () => {
  const fonts = fakeFonts();
  const gate = labelFaceGate({ fonts, faces: ['face'], timeoutMs: 1000 });

  let redraws = 0;
  gate.whenLate(() => {
    redraws += 1;
  });

  await tick(40);
  assert.deepEqual(fonts.asked, ['face']);
  assert.equal(redraws, 1);
});
