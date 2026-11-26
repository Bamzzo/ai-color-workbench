import { mountWorkbench } from "./app/workbench";

const root = document.getElementById("app");
if (!root) {
  throw new Error("#app 未找到");
}
mountWorkbench(root);