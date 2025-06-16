import { useState } from "react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface ApiKeysDialogProps {
  isOpen: boolean;
  onClose: () => void;
}

const ApiKeysDialog = ({ isOpen, onClose }: ApiKeysDialogProps) => {
  const [apiKeys, setApiKeys] = useState({
    ANTHROPIC_API_KEY: "",
    OPENAI_API_KEY: "",
    FIRECRAWL_API_KEY: "",
    SERPAPI_API_KEY: "",
    TAVILY_API_KEY: "",
    GEMINI_API_KEY: "",
  });
  const [isSaving, setIsSaving] = useState(false);

  const handleApiKeyChange = (key: string, value: string) => {
    setApiKeys({
      ...apiKeys,
      [key]: value,
    });
  };

  const saveApiKeys = async () => {
    try {
      setIsSaving(true);
      const response = await fetch("/api/settings/api-keys", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(apiKeys),
      });

      if (response.ok) {
        toast.success("API keys saved successfully");
        onClose();
      } else {
        throw new Error("Failed to save API keys");
      }
    } catch (error) {
      console.error("Error saving API keys:", error);
      toast.error("Failed to save API keys. Please try again.");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="bg-[#1e1f23] border-[#3A3B3F] text-white sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle className="text-xl font-semibold">API Keys</DialogTitle>
          <DialogDescription className="text-gray-400">
            Enter your API keys for various services. These keys will be stored
            securely.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 my-4 max-h-[60vh] overflow-y-auto pr-2">
          <div className="space-y-2">
            <Label htmlFor="anthropic-key">Anthropic API Key</Label>
            <Input
              id="anthropic-key"
              type="password"
              value={apiKeys.ANTHROPIC_API_KEY}
              onChange={(e) =>
                handleApiKeyChange("ANTHROPIC_API_KEY", e.target.value)
              }
              placeholder="Enter Anthropic API Key"
              className="bg-[#35363a] border-[#ffffff0f]"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="openai-key">OpenAI API Key</Label>
            <Input
              id="openai-key"
              type="password"
              value={apiKeys.OPENAI_API_KEY}
              onChange={(e) =>
                handleApiKeyChange("OPENAI_API_KEY", e.target.value)
              }
              placeholder="Enter OpenAI API Key"
              className="bg-[#35363a] border-[#ffffff0f]"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="gemini-key">Gemini API Key</Label>
            <Input
              id="gemini-key"
              type="password"
              value={apiKeys.GEMINI_API_KEY}
              onChange={(e) =>
                handleApiKeyChange("GEMINI_API_KEY", e.target.value)
              }
              placeholder="Enter Gemini API Key"
              className="bg-[#35363a] border-[#ffffff0f]"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="tavily-key">Tavily API Key</Label>
            <Input
              id="tavily-key"
              type="password"
              value={apiKeys.TAVILY_API_KEY}
              onChange={(e) =>
                handleApiKeyChange("TAVILY_API_KEY", e.target.value)
              }
              placeholder="Enter Tavily API Key"
              className="bg-[#35363a] border-[#ffffff0f]"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="firecrawl-key">FireCrawl API Key</Label>
            <Input
              id="firecrawl-key"
              type="password"
              value={apiKeys.FIRECRAWL_API_KEY}
              onChange={(e) =>
                handleApiKeyChange("FIRECRAWL_API_KEY", e.target.value)
              }
              placeholder="Enter FireCrawl API Key"
              className="bg-[#35363a] border-[#ffffff0f]"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="serpapi-key">SerpAPI API Key</Label>
            <Input
              id="serpapi-key"
              type="password"
              value={apiKeys.SERPAPI_API_KEY}
              onChange={(e) =>
                handleApiKeyChange("SERPAPI_API_KEY", e.target.value)
              }
              placeholder="Enter SerpAPI API Key"
              className="bg-[#35363a] border-[#ffffff0f]"
            />
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={onClose}
            className="border-[#ffffff0f]"
          >
            Cancel
          </Button>
          <Button onClick={saveApiKeys} disabled={isSaving}>
            {isSaving ? "Saving..." : "Save API Keys"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default ApiKeysDialog;
