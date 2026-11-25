open Js_of_ocaml

let document = Js.Unsafe.coerce Dom_html.document
let window = Js.Unsafe.coerce Dom_html.window
let inject = Js.Unsafe.inject

let query selector =
  Js.Unsafe.meth_call document "querySelector" [| inject (Js.string selector) |]

let create tag =
  Js.Unsafe.meth_call document "createElement" [| inject (Js.string tag) |]

let append parent child =
  ignore (Js.Unsafe.meth_call parent "appendChild" [| inject child |])

let set element key value = Js.Unsafe.set element key value
let set_text element value = set element "textContent" (Js.string value)
let set_attr element key value =
  ignore (Js.Unsafe.meth_call element "setAttribute" [| inject (Js.string key); inject (Js.string value) |])

let make_element tag class_name id =
  let element = create tag in
  set element "className" (Js.string class_name);
  if id <> "" then set element "id" (Js.string id);
  element

let listen element event callback =
  ignore (Js.Unsafe.meth_call element "addEventListener"
    [| inject (Js.string event); inject callback |])
let input_value selector =
  Js.to_string (Js.Unsafe.coerce (Js.Unsafe.get (query selector) "value"))

let dock_tabs = [
  ("ledger", "Cost Ledger", "Run costs by stage, model, and node");
  ("inspector", "Node Inspector", "Sections, reviews, verification, and notes");
  ("log", "Run Log", "Live events and execution messages");
]

let rec activate_panel selected tabs =
  match tabs with
  | [] -> ()
  | (key, _, _) :: rest ->
      let panel = query ("#reference-" ^ key ^ "-panel") in
      let button = query ("#reference-tab-" ^ key) in
      set panel "hidden" (Js.bool (key <> selected));
      set_attr button "aria-selected" (if key = selected then "true" else "false");
      set button "className" (Js.string (if key = selected then "reference-dock-tab active" else "reference-dock-tab"));
      activate_panel selected rest

let add_tab header (key, label, description) =
  let button = make_element "button" "reference-dock-tab" ("reference-tab-" ^ key) in
  set button "type" (Js.string "button");
  set_attr button "role" "tab";
  set_attr button "aria-controls" ("reference-" ^ key ^ "-panel");
  set_attr button "aria-label" description;
  set_text button label;
  let callback = Js.wrap_callback (fun (_ : Dom_html.event Js.t) -> activate_panel key dock_tabs; Js._false) in
  set button "onclick" (Js.Unsafe.inject callback);
  append header button

let has_class element class_name =
  let class_list = Js.Unsafe.get element "classList" in
  Js.to_bool (Js.Unsafe.coerce (Js.Unsafe.meth_call class_list "contains" [| inject (Js.string class_name) |]))

let decorate_tablist container_selector label tabs =
  let container = query container_selector in
  set_attr container "role" "tablist";
  set_attr container "aria-label" label;
  let refresh () =
    List.iter (fun (tab_selector, panel_id) ->
      let tab = query tab_selector in
      let active = has_class tab "active" in
      let panel = query ("#" ^ panel_id) in
      set_attr tab "role" "tab";
      set_attr tab "aria-controls" panel_id;
      set_attr tab "aria-selected" (if active then "true" else "false");
      set_attr tab "tabindex" (if active then "0" else "-1");
      set_attr panel "role" "tabpanel";
      set_attr panel "aria-labelledby" (String.sub tab_selector 1 (String.length tab_selector - 1))
    ) tabs
  in
  List.iter (fun (tab_selector, _) ->
    let tab = query tab_selector in
    let click_callback = Js.wrap_callback (fun (_ : Dom_html.event Js.t) -> refresh (); Js._false) in
    let key_callback = Js.wrap_callback (fun (event : Dom_html.event Js.t) ->
      let key = Js.to_string (Js.Unsafe.coerce (Js.Unsafe.get event "key")) in
      if key = "Enter" || key = " " then ignore (Js.Unsafe.meth_call tab "click" [||]);
      Js._false
    ) in
    listen tab "click" click_callback;
    listen tab "keydown" key_callback
  ) tabs;
  refresh ()

let move selector destination = append (query destination) (query selector)

let mount_workbench () =
  let main = query ".main-workspace" in
  let workbench = make_element "div" "reference-workbench" "reference-workbench" in
  let proof = make_element "section" "reference-surface reference-proof-surface" "reference-proof-surface" in
  let graph = make_element "section" "reference-surface reference-graph-surface" "reference-graph-surface" in
  let dock = make_element "section" "reference-surface reference-dock-surface" "reference-dock-surface" in
  let dock_header = make_element "div" "reference-dock-header" "reference-dock-header" in
  let dock_title = make_element "div" "reference-dock-title" "" in
  set_text dock_title "Run analysis";
  let dock_tabs_bar = make_element "div" "reference-dock-tabs" "reference-dock-tabs" in
  set_attr dock_tabs_bar "role" "tablist";
  set_attr dock_tabs_bar "aria-label" "Workspace panels";
  let dock_body = make_element "div" "reference-dock-body" "reference-dock-body" in
  let ledger = make_element "div" "reference-dock-panel reference-ledger-panel" "reference-ledger-panel" in
  let inspector = make_element "div" "reference-dock-panel" "reference-inspector-panel" in
  let log = make_element "div" "reference-dock-panel" "reference-log-panel" in

  append main workbench;
  append workbench proof;
  append workbench graph;
  append workbench dock;
  append dock_header dock_title;
  append dock_header dock_tabs_bar;
  append dock dock_header;
  append dock dock_body;
  append dock_body ledger;
  append dock_body inspector;
  append dock_body log;

  move "#preview-pane" "#reference-proof-surface";
  move "#left-pane" "#reference-graph-surface";
  move "#modal-ledger" "#reference-ledger-panel";
  move "#inspector-container" "#reference-inspector-panel";
  move "#right-pane > .sunken-frame:last-child" "#reference-log-panel";

  let ledger_root = query "#modal-ledger" in
  set ledger_root "className" (Js.string "reference-docked-ledger");
  let ledger_title = query "#modal-ledger .modal-header span" in
  set_text ledger_title "Cost Ledger";
  let preview_title = query "#preview-pane .pane-titlebar strong" in
  set_text preview_title "LaTeX Proof Viewer";

  let proof_hero = make_element "article" "reference-proof-hero" "reference-proof-hero" in
  let hero_kicker = make_element "p" "reference-proof-hero-kicker" "" in
  let hero_title = make_element "h2" "reference-proof-hero-title" "" in
  let hero_copy = make_element "p" "reference-proof-hero-copy" "" in
  set_text hero_kicker "MINI-COLOSSEUM · RESEARCH WORKSPACE";
  set_text hero_title "A question becomes a proof.";
  set_text hero_copy "Follow each idea from exploration through review, revision, and verification.";
  append proof_hero hero_kicker;
  append proof_hero hero_title;
  append proof_hero hero_copy;
  append (query "#live-preview-content") proof_hero;
  let sync_hero () =
    let problem = String.trim (input_value "#toolbar-problem-title") in
    set proof_hero "hidden" (Js.bool (problem <> ""))
  in
  let hero_callback = Js.wrap_callback (fun (_ : Dom_html.event Js.t) -> sync_hero (); Js._false) in
  listen (query "#toolbar-problem-title") "input" hero_callback;
  listen (query "#input-problem") "input" hero_callback;
  sync_hero ();

  decorate_tablist ".tab-strip" "Proof views" [
    ("#tab-btn-tree", "tab-tree");
    ("#tab-btn-dag", "tab-dag");
    ("#tab-btn-doc", "tab-doc");
  ];
  decorate_tablist "#reference-inspector-panel .subgoal-tabs-bar" "Node inspector views" [
    ("#tab-insp-goals", "view-insp-goals");
    ("#tab-insp-details", "view-insp-details");
    ("#tab-insp-falsifier", "view-insp-falsifier");
    ("#tab-insp-verifier", "view-insp-verifier");
    ("#tab-insp-hmed", "view-insp-hmed");
    ("#tab-insp-knowledge", "view-insp-knowledge");
  ];

  List.iter (add_tab dock_tabs_bar) dock_tabs;
  activate_panel "ledger" dock_tabs;

  let ledger_button = query ".toolbar button[title='Open cost ledger']" in
  let ledger_callback = Js.wrap_callback (fun (_ : Dom_html.event Js.t) -> activate_panel "ledger" dock_tabs; Js._false) in
  ignore (Js.Unsafe.meth_call ledger_button "addEventListener"
    [| inject (Js.string "click"); inject ledger_callback; inject (Js.bool true) |]);

  let disclaimer = make_element "div" "reference-transparency" "reference-transparency" in
  set_text disclaimer "AI-assisted review · Formal verification is not guaranteed";
  append proof disclaimer;

  set_attr workbench "aria-label" "Mini-Colosseum proof workspace";
  set_attr proof "aria-label" "LaTeX proof viewer";
  set_attr graph "aria-label" "Live proof dependency graph";
  set_attr dock "aria-label" "Run analysis panels";
  Js._false

let () =
  let callback = Js.wrap_callback (fun (_ : Dom_html.event Js.t) -> mount_workbench ()) in
  ignore (Js.Unsafe.meth_call window "addEventListener"
    [| inject (Js.string "DOMContentLoaded"); inject callback; inject (Js.bool false) |])
