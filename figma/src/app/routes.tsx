import { createBrowserRouter } from "react-router";
import { LoginPage } from "./components/login-page";
import { HomePage } from "./components/home-page";
import { Layout } from "./components/layout";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: Layout,
    children: [
      { index: true, Component: LoginPage },
      { path: "home", Component: HomePage },
    ],
  },
]);
