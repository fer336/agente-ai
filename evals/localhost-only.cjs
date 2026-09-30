// Preload for `promptfoo view`: forces TCP servers to listen on 127.0.0.1
// (promptfoo binds 0.0.0.0 by default). Use with NODE_OPTIONS=--require <this file>.
//
// Covered forms: listen(), listen(cb), listen(port[, host][, backlog][, cb]) and
// listen(options). Any host the caller passed is replaced by 127.0.0.1.
// Left untouched on purpose (not TCP host/port binds): IPC paths (a non-numeric
// string or options.path), file descriptors / handles (options.fd, objects with
// `_handle` or `fd`).
const net = require('net');

const HOST = '127.0.0.1';
const originalListen = net.Server.prototype.listen;

function isPort(value) {
  return typeof value === 'number' || (typeof value === 'string' && /^\d+$/.test(value));
}

net.Server.prototype.listen = function listen(...args) {
  const cb = typeof args[args.length - 1] === 'function' ? args.pop() : undefined;
  const first = args[0];
  let next;

  if (first === undefined || first === null || isPort(first)) {
    // listen([port[, host][, backlog]][, cb])
    const rest = args.slice(1);
    if (typeof rest[0] === 'string') rest.shift(); // caller's host, replaced
    next = [first ?? 0, HOST, ...rest.filter((v) => typeof v === 'number')];
  } else if (typeof first === 'object' && !('path' in first) && !('fd' in first) &&
             !('_handle' in first)) {
    next = [{ ...first, host: HOST }];
  } else {
    next = args; // IPC path / handle: untouched
  }
  if (cb) next.push(cb);
  return originalListen.apply(this, next);
};
