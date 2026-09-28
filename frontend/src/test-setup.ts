import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Testing Library unmounts rendered trees automatically only when test globals are enabled.
// They are not, so without this a previous test's app (and its router) stays mounted and
// reacts to the next test's navigation.
afterEach(cleanup);

// jsdom does not implement scrolling; the router calls it on navigation.
window.scrollTo = () => undefined;
