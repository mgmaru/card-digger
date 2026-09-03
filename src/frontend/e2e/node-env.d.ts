/**
 * The one piece of Node's global surface this configuration touches.
 *
 * `@types/node` would add a package to the fixed list in MVP specification
 * section 2.2 to describe a whole runtime, where what is actually read is one
 * environment variable. Declaring only that keeps the surface visible: if a
 * second variable appears here, it has to be written down.
 */
declare const process: { env: { CI?: string } };
