/** Per-conversation coalesced writes so last user intent is the durable result. */

export function createPerConversationWriteQueue({ write } = {}) {
  if (typeof write !== "function") {
    throw new Error("write function is required");
  }
  const tails = new Map();
  const pending = new Map();
  const generations = new Map();

  function enqueue(conversationId, payload) {
    if (!conversationId) return Promise.resolve(undefined);
    const generation = (generations.get(conversationId) || 0) + 1;
    generations.set(conversationId, generation);
    pending.set(conversationId, { payload, generation });
    const previous = tails.get(conversationId) || Promise.resolve();
    const next = previous.catch(() => undefined).then(async () => {
      const queued = pending.get(conversationId);
      if (!queued || queued.generation !== generation) return undefined;
      pending.delete(conversationId);
      return write(conversationId, queued.payload);
    });
    tails.set(conversationId, next);
    return next;
  }

  return { enqueue };
}
