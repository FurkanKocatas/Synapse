// Compiles the message files into typed functions under src/paraglide/.
// Runs before type checking, linting and tests, which import the generated code.
import { compile } from "@inlang/paraglide-js";

import { paraglideOptions } from "../paraglide.options.js";

await compile(paraglideOptions);
