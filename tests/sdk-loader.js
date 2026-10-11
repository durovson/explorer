// Local-only loader. The deployed tgcloud tree contains no test/runtime dependencies.
const mockURL = new URL('./sdk-mock.js', import.meta.url).href;
export async function resolve(specifier, context, nextResolve) {
  if (specifier === 'sdk' || specifier === 'sdk/db') return { url: mockURL, shortCircuit: true };
  return nextResolve(specifier, context);
}
