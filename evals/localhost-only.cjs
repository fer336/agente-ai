// Preload for `promptfoo view`: forces every net.Server to listen on 127.0.0.1
// (promptfoo binds 0.0.0.0 by default). Use with NODE_OPTIONS=--require <this file>.
const net = require('net');

const HOST = '127.0.0.1';
const originalListen = net.Server.prototype.listen;

net.Server.prototype.listen = function listen(...args) {
  const first = args[0];
  if (first !== null && typeof first === 'object' && !Array.isArray(first)) {
    // listen({ port, host, ... }) -- unix sockets (path) are left alone.
    if (first.path === undefined) {
      args[0] = { ...first, host: HOST };
    }
  } else if (typeof first === 'number' || (typeof first === 'string' && /^\d+$/.test(first))) {
    // listen(port[, host][, backlog][, cb])
    const rest = args.slice(1);
    if (typeof rest[0] === 'string') {
      rest[0] = HOST;
    } else {
      rest.unshift(HOST);
    }
    args = [first, ...rest];
  }
  return originalListen.apply(this, args);
};
