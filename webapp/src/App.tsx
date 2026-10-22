import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useCurrentWorkspaceId } from "./api/useCurrentWorkspaceId";
import { TokenGate } from "./auth/TokenGate";
import { AdminShell } from "./layout/AdminShell";
import { AppShell } from "./layout/AppShell";
import { Dashboard } from "./pages/Dashboard";
import { NewWorkspace } from "./pages/admin/NewWorkspace";
import { AdminSettings } from "./pages/admin/Settings";
import { AdminUsers } from "./pages/admin/Users";
import { StatisticsPage } from "./pages/admin/Statistics";
import { DocumentReshape } from "./pages/documents/Reshape";
import { DocumentTemplatePage, DocumentTemplates } from "./pages/documents/Templates";
import { AdminWorkspaces } from "./pages/admin/Workspaces";
import { ExportDetailPage } from "./pages/admin/portability/ExportDetail";
import { ImportDetailPage } from "./pages/admin/portability/ImportDetail";
import { PortabilityPage } from "./pages/admin/portability/Portability";
import { AssetDetail } from "./pages/assets/Detail";
import { AssetForm } from "./pages/assets/Form";
import { AssetSearch } from "./pages/assets/Search";
import { AdvancedSearch } from "./pages/search/Advanced";
import { MapPage } from "./pages/map/MapPage";
import { DocumentDetail } from "./pages/documents/Detail";
import { DocumentForm } from "./pages/documents/Form";
import { DocumentList } from "./pages/documents/List";
import { DocumentSearch } from "./pages/documents/Search";
import { DocumentSuggestions } from "./pages/documents/Suggestions";
import { GlobalValueForm } from "./pages/globalvalues/Form";
import { Ask } from "./pages/ai/Ask";
import { HelpPage } from "./pages/help/Help";
import { GraphExplorer } from "./pages/graph/Explorer";
import { BeamModelPage } from "./pages/beam/BeamModel";
import { BeamModelEditorPage } from "./pages/beam/BeamModelEditor";
import { BeamAssetSyncPage } from "./pages/beam/BeamAssetSync";
import { GlobalValueList } from "./pages/globalvalues/List";
import { ImportList } from "./pages/imports/List";
import { MarkdownImport } from "./pages/imports/Markdown";
import { ImportConfigForm } from "./pages/imports/New";
import { ImportStatus } from "./pages/imports/Status";
import { IssueBoard } from "./pages/issues/Board";
import { IssueDetail } from "./pages/issues/Detail";
import { IssueForm } from "./pages/issues/Form";
import { IssueList } from "./pages/issues/List";
import { IssueSearch } from "./pages/issues/Search";
import { LabelList } from "./pages/labels/List";
import { ReviewQueuePage } from "./pages/review/Queue";
import { MigrationPage } from "./pages/migration/Domains";
import { SpreadsheetImportPage } from "./pages/assets/SpreadsheetImport";
import { CatalogueMappingPage } from "./pages/migration/CatalogueMapping";
import { ControlBindingsPage } from "./pages/review/ControlBindings";
import { TypeCataloguePage } from "./pages/catalogue/TypeCatalogue";
import { AboutPage } from "./pages/about/About";
import { CatalogueMappingReview } from "./pages/migration/CatalogueMappingReview";
import { BulkChangesPage } from "./pages/bulk/BulkChanges";
import { WorkflowsPage } from "./pages/workflows/Workflows";
import { LookupPage } from "./pages/lookup/Lookup";
import { LinkRedirect } from "./pages/lookup/LinkRedirect";
import { SchemaDetail } from "./pages/schemas/Detail";
import { IconLibrary } from "./pages/icons/List";
import { SchemaForm } from "./pages/schemas/Form";
import { InstallationAI, WorkspaceAI } from "./pages/workspace/AI";
import { WorkspaceAccess } from "./pages/workspace/Access";
import { WorkspaceMembers } from "./pages/workspace/Members";
import { WorkspaceIntegrity } from "./pages/workspace/Integrity";
import { WorkspaceKeys } from "./pages/workspace/Keys";
import { WorkspacePackages } from "./pages/workspace/Packages";
import { GlpiPage } from "./pages/workspace/Glpi";
import { AccessReviews } from "./pages/workspace/AccessReviews";
import { EquipmentClassesPage } from "./pages/catalogue/EquipmentClasses";
import { WorkspaceTransfer } from "./pages/workspace/Transfer";
import { TransferList } from "./pages/workspace/TransferList";
import { TransferStatus } from "./pages/workspace/TransferStatus";
import { AccountPage } from "./pages/account/Account";
import { RobotTokensPage } from "./pages/workspace/RobotTokens";
import { AdminTokensPage } from "./pages/admin/Tokens";
import { PrintPage } from "./pages/Print";

/** Sends /imports/... to the workspace-scoped equivalent, keeping whatever
 * came after it. */
function LegacyImportRedirect() {
  const workspaceId = useCurrentWorkspaceId();
  const location = useLocation();
  if (!workspaceId) return null;
  const rest = location.pathname.replace(/^\/imports/, "");
  return (
    <Navigate
      to={`/workspaces/${workspaceId}/imports${rest}${location.search}`}
      replace
    />
  );
}

export function App() {
  return (
    <TokenGate>
      <Routes>
        {/* Export ▸ PDF / Print: the record alone on the page, no app around it. */}
        <Route path="/print/:kind/:uid" element={<PrintPage />} />
        <Route element={<AppShell />}>
          <Route path="/" element={<Dashboard />} />

          <Route path="/ask" element={<Ask />} />
          <Route path="/help" element={<HelpPage />} />
          <Route path="/help/:slug" element={<HelpPage />} />

          <Route path="/schemas/new" element={<SchemaForm />} />
          <Route path="/schemas/:uid" element={<SchemaDetail />} />
          <Route path="/schemas/:uid/edit" element={<SchemaForm />} />

          <Route path="/assets/search" element={<AssetSearch />} />
          <Route path="/search/advanced" element={<AdvancedSearch />} />
          <Route path="/map" element={<MapPage />} />
          <Route path="/assets/new" element={<AssetForm />} />
          <Route path="/assets/import" element={<SpreadsheetImportPage />} />
          <Route path="/assets/:uid" element={<AssetDetail />} />
          <Route path="/assets/:uid/edit" element={<AssetForm />} />

          <Route path="/tickets" element={<IssueList />} />
          <Route path="/tickets/board" element={<IssueBoard />} />
          <Route path="/tickets/workflows" element={<WorkflowsPage />} />
          <Route path="/tickets/search" element={<IssueSearch />} />
          <Route path="/tickets/new" element={<IssueForm />} />
          <Route path="/tickets/:uid" element={<IssueDetail />} />
          <Route path="/tickets/:uid/edit" element={<IssueForm />} />

          <Route path="/documents" element={<DocumentList />} />
          <Route path="/documents/search" element={<DocumentSearch />} />
          <Route path="/documents/suggestions" element={<DocumentSuggestions />} />
          <Route path="/documents/new" element={<DocumentForm />} />
          <Route path="/documents/reshape" element={<DocumentReshape />} />
          <Route path="/documents/templates" element={<DocumentTemplates />} />
          <Route path="/documents/templates/:ref" element={<DocumentTemplatePage />} />
          <Route path="/documents/:uid" element={<DocumentDetail />} />

          <Route path="/graph" element={<GraphExplorer />} />
          <Route path="/beam-model" element={<BeamModelPage />} />
          <Route path="/beam-model/new" element={<BeamModelEditorPage />} />
          <Route path="/beam-model/edit/:modelId" element={<BeamModelEditorPage />} />
          <Route path="/beam-model/:modelId/assets" element={<BeamAssetSyncPage />} />
          <Route path="/review" element={<ReviewQueuePage />} />
          {/* Moved under Administration; an old link still lands there. */}
          <Route path="/migration" element={<Navigate to="/admin/migration" replace />} />
          <Route path="/migration/catalogue" element={<CatalogueMappingPage />} />
          <Route path="/control-bindings" element={<ControlBindingsPage />} />
          <Route path="/catalogue/types" element={<TypeCataloguePage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/account" element={<AccountPage />} />
          <Route path="/migration/catalogue/:id" element={<CatalogueMappingReview />} />
          <Route path="/bulk-changes" element={<BulkChangesPage />} />
          <Route path="/catalogue/equipment-classes" element={<EquipmentClassesPage />} />
          <Route path="/lookup/*" element={<LookupPage />} />
          {["/asset/:id", "/position/:id", "/installation/:id", "/document/:id", "/ticket/*", "/review/:id"].map((p) => (
            <Route key={p} path={p} element={<LinkRedirect />} />
          ))}

          <Route path="/labels" element={<LabelList />} />

          <Route path="/global-values" element={<GlobalValueList />} />
          <Route path="/global-values/new" element={<GlobalValueForm />} />
          <Route path="/global-values/:uid/edit" element={<GlobalValueForm />} />

          {/* Imports moved under the workspace's settings; old links and
              bookmarks still land in the right place. */}
          <Route path="/imports/*" element={<LegacyImportRedirect />} />
        </Route>

        <Route element={<AdminShell />}>
          <Route path="/workspaces/:workspaceId/imports" element={<ImportList />} />
          <Route path="/workspaces/:workspaceId/imports/new" element={<ImportConfigForm />} />
          <Route path="/workspaces/:workspaceId/imports/markdown" element={<MarkdownImport />} />
          <Route
            path="/workspaces/:workspaceId/imports/configs/:uid/edit"
            element={<ImportConfigForm />}
          />
          <Route path="/workspaces/:workspaceId/imports/:uid" element={<ImportStatus />} />
          <Route path="/workspaces/:workspaceId/ai" element={<WorkspaceAI />} />
          <Route path="/workspaces/:workspaceId/robot-tokens" element={<RobotTokensPage />} />
          <Route path="/workspaces/:workspaceId/access" element={<WorkspaceAccess />} />
          <Route path="/workspaces/:workspaceId/access-reviews" element={<AccessReviews />} />
          <Route path="/workspaces/:workspaceId/members" element={<WorkspaceMembers />} />
          <Route path="/workspaces/:workspaceId/integrity" element={<WorkspaceIntegrity />} />
          <Route path="/workspaces/:workspaceId/keys" element={<WorkspaceKeys />} />
          <Route path="/workspaces/:workspaceId/packages" element={<WorkspacePackages />} />
          <Route path="/workspaces/:workspaceId/glpi" element={<GlpiPage />} />
          <Route path="/workspaces/:workspaceId/icons" element={<IconLibrary />} />
          <Route path="/workspaces/:workspaceId/transfer" element={<WorkspaceTransfer />} />
          <Route path="/workspaces/:workspaceId/transfers" element={<TransferList />} />
          <Route path="/workspaces/:workspaceId/transfers/:uid" element={<TransferStatus />} />
          <Route path="/admin/workspaces" element={<AdminWorkspaces />} />
          <Route path="/admin/new-workspace" element={<NewWorkspace />} />
          <Route path="/admin/users" element={<AdminUsers />} />
          <Route path="/admin/statistics" element={<StatisticsPage />} />
          <Route path="/admin/settings" element={<AdminSettings />} />
          <Route path="/admin/ai" element={<InstallationAI />} />
          <Route path="/admin/tokens" element={<AdminTokensPage />} />
          <Route path="/admin/portability" element={<PortabilityPage />} />
          <Route path="/admin/migration" element={<MigrationPage />} />
          <Route path="/admin/portability/exports/:id" element={<ExportDetailPage />} />
          <Route path="/admin/portability/imports/:id" element={<ImportDetailPage />} />
        </Route>
      </Routes>
    </TokenGate>
  );
}
